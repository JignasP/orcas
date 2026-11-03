"""Prometheus metrics for the retrieval service (F8, D5; freshness and ingest throughput D2).

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
DOC_CHUNKS = Gauge(
    "orcas_index_document_chunks",
    "Chunks per indexed document; labels name the pinned version and source checksum",
    ["doc_id", "version", "sha256"],
)
INGEST_CHUNKS_PER_S = Gauge("orcas_ingest_chunks_per_second", "Throughput of the last ingest (chunks/s)")
INGEST_PAGES_PER_S = Gauge("orcas_ingest_pages_per_second", "Throughput of the last ingest (pages/s)")
INGEST_ELAPSED = Gauge("orcas_ingest_elapsed_seconds", "Duration of the last ingest")
INGEST_EMBEDDED = Gauge("orcas_ingest_embedded_chunks", "Chunks the last ingest embedded (0 if unchanged)")


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
    DOC_CHUNKS.clear()  # drop documents no longer in the index
    for doc in info.get("documents", []):
        DOC_CHUNKS.labels(doc.get("doc_id", ""), doc.get("version", ""),
                          (doc.get("source_sha256") or "")[:12]).set(doc.get("chunk_count") or 0)
    throughput = info.get("throughput") or {}
    for gauge, key in ((INGEST_CHUNKS_PER_S, "chunks_per_s"), (INGEST_PAGES_PER_S, "pages_per_s"),
                       (INGEST_ELAPSED, "elapsed_s"), (INGEST_EMBEDDED, "embedded")):
        if key in throughput:
            gauge.set(throughput[key])
