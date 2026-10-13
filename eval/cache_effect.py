"""Retrieval cache effect (D7): hit ratio + latency, cold vs warm.

Runs the scenario queries twice against a retriever with a fresh in-memory cache: the first
pass is all misses (cold), the second all hits (warm). Reports hit ratio and p50/p95 latency.
With REDIS_URL set the same numbers come from the shared Redis cache.

Run:  python -m eval.cache_effect
"""
from __future__ import annotations

import yaml

from services.corpus_common.constants import repo_root
from services.retrieval.cache import InMemoryTTLCache
from services.retrieval.models import SearchFilters, SearchRequest
from services.retrieval.service import Retriever


def _p(latencies, q):
    s = sorted(latencies)
    return round(s[min(len(s) - 1, int(q * len(s)))], 2) if s else 0.0


def main(argv=None) -> int:
    scenarios = yaml.safe_load((repo_root() / "eval" / "scenarios.yaml").read_text())["scenarios"]
    cache = InMemoryTTLCache()
    r = Retriever(cache=cache)
    reqs = [SearchRequest(query=s["complaint_text"], k=5,
                          filters=SearchFilters(framework=s["expected_regulator"])
                          if s["expected_regulator"] in ("SEBI", "RBI") else None)
            for s in scenarios]

    def sweep():
        lat, hits = [], 0
        for req in reqs:
            resp = r.search(req)
            lat.append(resp.latency_ms)
            hits += int(resp.cache_hit)
        return lat, hits

    cache.clear()
    cold_lat, cold_hits = sweep()
    warm_lat, warm_hits = sweep()

    n = len(reqs)
    print(f"\n=== Retrieval cache effect (n={n} queries) ===")
    print(f"{'':<8}{'hit_ratio':>12}{'p50_ms':>10}{'p95_ms':>10}{'mean_ms':>10}")
    for label, lat, hits in [("cold", cold_lat, cold_hits), ("warm", warm_lat, warm_hits)]:
        print(f"{label:<8}{hits / n:>12.2f}{_p(lat, .5):>10}{_p(lat, .95):>10}"
              f"{round(sum(lat) / n, 2):>10}")
    speedup = (sum(cold_lat) / n) / max(1e-6, (sum(warm_lat) / n))
    print(f"\nwarm mean speedup vs cold: {speedup:.1f}x (key = normalised query + filters + index_version)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
