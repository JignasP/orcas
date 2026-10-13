"""Retrieval cache (D7).

Key = sha256(normalised_query | filters | mode | k | index_version), exactly the key
described in the architecture, so a changed index_version transparently invalidates stale
entries. Backend is Redis when ``REDIS_URL`` is set (shared across workers, the production
choice), otherwise a process-local TTL dict so retrieval works standalone and in tests.
Effect (hit ratio, latency) is measured in eval/cache_effect.py.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Dict, Optional

DEFAULT_TTL_S = int(os.getenv("RETRIEVAL_CACHE_TTL_S", "300"))


def make_key(query: str, filters: Dict[str, Any], mode: str, k: int, index_version: str) -> str:
    norm_q = " ".join((query or "").lower().split())
    payload = json.dumps(
        {"q": norm_q, "f": filters or {}, "m": mode, "k": k, "iv": index_version},
        sort_keys=True,
    )
    return "orcas:retr:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


class InMemoryTTLCache:
    def __init__(self, ttl_s: int = DEFAULT_TTL_S):
        self.ttl = ttl_s
        self._d: Dict[str, tuple] = {}

    def get(self, key: str) -> Optional[dict]:
        hit = self._d.get(key)
        if not hit:
            return None
        value, expiry = hit
        if expiry and time.time() > expiry:
            self._d.pop(key, None)
            return None
        return value

    def set(self, key: str, value: dict) -> None:
        expiry = time.time() + self.ttl if self.ttl else 0
        self._d[key] = (value, expiry)

    def clear(self) -> None:
        self._d.clear()


class RedisCache:
    def __init__(self, url: str, ttl_s: int = DEFAULT_TTL_S):
        import redis  # imported only when REDIS_URL is set

        self.ttl = ttl_s
        self._r = redis.Redis.from_url(url)

    def get(self, key: str) -> Optional[dict]:
        raw = self._r.get(key)
        return json.loads(raw) if raw else None

    def set(self, key: str, value: dict) -> None:
        self._r.set(key, json.dumps(value), ex=self.ttl or None)

    def clear(self) -> None:
        for k in self._r.scan_iter("orcas:retr:*"):
            self._r.delete(k)


_CACHE = None


def get_cache():
    """Process-wide cache singleton selected by environment."""
    global _CACHE
    if _CACHE is None:
        url = os.getenv("REDIS_URL")
        _CACHE = RedisCache(url) if url else InMemoryTTLCache()
    return _CACHE
