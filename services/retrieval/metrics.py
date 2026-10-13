"""Prometheus metrics for the retrieval service (F8, D5; freshness D2).

Metric names use the `orcas_` prefix agreed in ARCHITECTURE.md §8. The cache
counters exist from v0 (always a miss until the Slice-6 Redis cache lands) so the
hit-ratio panel has a stable series name.
"""
from __future__ import annotations

from datetime import datetime

from prometheus_client import Counter, Gauge, Histogram

from services.corpus_common import store

REQUESTS = Counter(
    "orcas_retrieval_requests_total", "Retrieval requests", ["endpoint", "status"]
)
SEARCH_LATENCY = Histogram(
    "orcas_retrieval_latency_seconds",
    "Search latency (seconds)",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)
RESULTS_PER_QUERY = Histogram(
    "orcas_retrieval_results_per_query",
    "Results returned per query",
    buckets=(0, 1, 2, 4, 8, 16, 32, 50),
)
CACHE_HITS = Counter("orcas_retrieval_cache_hits_total", "Retrieval cache hits")
CACHE_MISSES = Counter("orcas_retrieval_cache_misses_total", "Retrieval cache misses")

INDEX_CHUNKS = Gauge("orcas_index_chunks", "Number of chunks in the index")
INDEX_BUILT_TS = Gauge(
    "orcas_index_built_timestamp", "Index build time (unix seconds)"
)


def refresh_index_gauges() -> None:
    info = store.read_index_info() or {}
    if "chunk_count" in info:
        INDEX_CHUNKS.set(info.get("chunk_count") or 0)
    built_at = info.get("built_at")
    if built_at:
        try:
            INDEX_BUILT_TS.set(datetime.fromisoformat(built_at).timestamp())
        except ValueError:
            pass
