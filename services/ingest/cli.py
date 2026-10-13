"""orcas-ingest CLI (v0): parse -> naive chunk -> MiniLM embed -> upsert to Chroma.

Idempotent: chunk ids are content hashes, so a second run on an unchanged corpus
upserts the same ids and reports "no changes". Re-chunking deletes a document's
now-stale chunks so no orphans survive.

Usage (from repo root, with the venv active):
    python -m services.ingest                         # index all indexed_ready docs
    python -m services.ingest --reindex-if-changed    # same (idempotent)
    python -m services.ingest --re-embed --model-tag minilm-l6-v2
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from typing import List

from services.corpus_common import store
from services.corpus_common.constants import (
    DISTANCE_METRIC,
    MODEL_NAME,
    MODEL_TAG,
    DEFAULT_COLLECTION,
)
from services.corpus_common.embedding import embed_texts
from services.corpus_common.store import ChunkRecord
from .chunk import chunk_pages
from .manifest import indexable, load_manifest
from .parse import extracted_char_count, parse_pdf


def _upsert_batched(col, records: List[ChunkRecord], batch: int = 128) -> None:
    for i in range(0, len(records), batch):
        chunk = records[i : i + batch]
        col.upsert(
            ids=[r.chunk_id for r in chunk],
            embeddings=embed_texts([r.text for r in chunk]),
            documents=[r.text for r in chunk],
            metadatas=[r.to_metadata() for r in chunk],
        )


def run(args: argparse.Namespace) -> int:
    model_tag = args.model_tag or MODEL_TAG
    docs = indexable(load_manifest(args.corpus))
    if not docs:
        print("ingest: no indexed_ready documents found in manifest", file=sys.stderr)
        return 1

    client = store.get_client(args.chroma_dir)
    col = store.get_collection(client, name=args.collection)

    print(
        f"ingest: loading embedding model ({MODEL_NAME}) and indexing {len(docs)} "
        f"document(s) — first run may take ~15-30s per large doc, please wait…",
        flush=True,
    )

    started = time.time()
    total_pages = 0
    total_chunks = 0
    total_added = 0
    total_stale = 0
    per_doc = []

    for d in docs:
        print(f"ingest: processing {d.doc_id} …", flush=True)
        pages = parse_pdf(d.path)
        records = chunk_pages(
            pages,
            doc_id=d.doc_id,
            doc_title=d.title,
            framework=d.framework,
            version=d.version,
            circular_ref=d.circular_ref,
            model_tag=model_tag,
            chunk_words=args.chunk_words,
            overlap=args.overlap,
        )
        desired_ids = {r.chunk_id for r in records}

        existing_ids = set(col.get(where={"doc_id": d.doc_id}, include=[])["ids"])
        added = len(desired_ids - existing_ids)
        stale = list(existing_ids - desired_ids)
        if stale:
            col.delete(ids=stale)

        _upsert_batched(col, records)

        total_pages += len(pages)
        total_chunks += len(records)
        total_added += added
        total_stale += len(stale)
        per_doc.append(
            {
                "doc_id": d.doc_id,
                "title": d.title,
                "framework": d.framework,
                "version": d.version,
                "chunk_count": len(records),
                "has_text_layer": d.has_text_layer,
                "source_sha256": d.source_sha256,
                "pages": len(pages),
                "extracted_chars": extracted_char_count(pages),
            }
        )
        print(
            f"ingest: {d.doc_id}: {len(pages)} pages -> {len(records)} chunks "
            f"(+{added} new, {len(stale)} stale removed)"
        )

    elapsed = max(time.time() - started, 1e-6)
    built_at = datetime.now(timezone.utc)
    index_version = (
        f"{model_tag}.{built_at.strftime('%Y%m%dT%H%M%SZ')}.{total_chunks}"
    )
    info = {
        "index_version": index_version,
        "built_at": built_at.isoformat(),
        "model_tag": model_tag,
        "embedding_model": MODEL_NAME,
        "distance_metric": DISTANCE_METRIC,
        "hybrid_enabled": False,
        "chunk_count": col.count(),
        "collection": args.collection,
        "throughput": {
            "chunks_per_s": round(total_chunks / elapsed, 2),
            "pages_per_s": round(total_pages / elapsed, 2),
            "elapsed_s": round(elapsed, 2),
        },
        "documents": per_doc,
    }
    store.write_index_info(info, args.index_info)

    changed = total_added > 0 or total_stale > 0
    print(
        f"ingest: done in {elapsed:.1f}s — {total_chunks} chunks across {len(docs)} docs; "
        f"collection now holds {col.count()}. "
        + ("CHANGED" if changed else "no changes (idempotent)")
    )
    print(f"ingest: index_version={index_version}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="orcas-ingest", description="ORCAS corpus ingest (v0)")
    p.add_argument("--corpus", default=None, help="corpus dir containing MANIFEST.yaml")
    p.add_argument("--chroma-dir", default=None, help="Chroma persistence dir")
    p.add_argument("--collection", default=DEFAULT_COLLECTION)
    p.add_argument("--index-info", default=None, help="path to write index_info.json")
    p.add_argument("--chunk-words", type=int, default=180)
    p.add_argument("--overlap", type=int, default=40)
    p.add_argument(
        "--reindex-if-changed",
        action="store_true",
        help="idempotent full pass (upsert-by-id already makes this a no-op when unchanged)",
    )
    p.add_argument(
        "--re-embed",
        action="store_true",
        help="re-embed using --model-tag (v0: recomputes ids for that tag; incremental by-id re-embed is Slice 4)",
    )
    p.add_argument("--model-tag", default=None, help="embedding model tag override")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return run(args)
