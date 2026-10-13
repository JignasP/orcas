"""orcas-ingest CLI: parse -> segment/chunk -> MiniLM embed -> upsert to Chroma.

Idempotent (content-hash ids). Two chunking strategies:
  --strategy clause  (default)  structure-aware clause-aligned segmentation + scope cards
  --strategy fixed              fixed-size word windows (the v0 baseline, kept for the A/B)

Re-embedding (no re-parse, by id):
  python -m services.ingest --re-embed --model-tag <tag>
re-embeds the stored chunk texts under <tag>. Same tag -> same ids -> vectors replaced in
place; a new tag -> new id set, old-tag chunks removed. No PDF is re-parsed.

Usage:
  python -m services.ingest
  python -m services.ingest --strategy fixed --collection orcas_fixed
  python -m services.ingest --re-embed --model-tag minilm-l6-v2
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List

from services.corpus_common import store
from services.corpus_common.constants import (
    DISTANCE_METRIC,
    MODEL_NAME,
    MODEL_TAG,
    DEFAULT_COLLECTION,
)
from services.corpus_common.embedding import embed_texts
from services.corpus_common.ids import chunk_id
from services.corpus_common.store import ChunkRecord
from .chunk import chunk_pages
from .manifest import ManifestDoc, indexable, load_manifest
from .metadata import build_scope_cards
from .parse import extracted_char_count, parse_pdf
from .segment import segment_pages


def _upsert_batched(col, records: List[ChunkRecord], batch: int = 128) -> None:
    for i in range(0, len(records), batch):
        chunk = records[i : i + batch]
        col.upsert(
            ids=[r.chunk_id for r in chunk],
            embeddings=embed_texts([r.text for r in chunk]),
            documents=[r.text for r in chunk],
            metadatas=[r.to_metadata() for r in chunk],
        )


def _write_index_info(col, args, model_tag, per_doc, elapsed, total_pages, total_chunks, strategy):
    built_at = datetime.now(timezone.utc)
    index_version = f"{model_tag}.{strategy}.{built_at.strftime('%Y%m%dT%H%M%SZ')}.{col.count()}"
    info = {
        "index_version": index_version,
        "built_at": built_at.isoformat(),
        "model_tag": model_tag,
        "embedding_model": MODEL_NAME,
        "distance_metric": DISTANCE_METRIC,
        "chunking_strategy": strategy,
        "hybrid_enabled": False,
        "chunk_count": col.count(),
        "collection": args.collection,
        "throughput": {
            "chunks_per_s": round(total_chunks / max(elapsed, 1e-6), 2),
            "pages_per_s": round(total_pages / max(elapsed, 1e-6), 2),
            "elapsed_s": round(elapsed, 2),
        },
        "documents": per_doc,
    }
    store.write_index_info(info, args.index_info)
    return index_version


def _sync_doc(col, doc_id: str, recs: List[ChunkRecord]):
    desired = {r.chunk_id for r in recs}
    existing = set(col.get(where={"doc_id": doc_id}, include=[])["ids"])
    stale = list(existing - desired)
    if stale:
        col.delete(ids=stale)
    _upsert_batched(col, recs)
    return len(desired - existing), len(stale)


def run(args: argparse.Namespace) -> int:
    model_tag = args.model_tag or MODEL_TAG
    client = store.get_client(args.chroma_dir)
    col = store.get_collection(client, name=args.collection)

    if args.re_embed:
        return _run_reembed(args, col, model_tag)

    docs = indexable(load_manifest(args.corpus))
    if not docs:
        print("ingest: no indexed_ready documents found in manifest", file=sys.stderr)
        return 1

    print(
        f"ingest: loading embedding model ({MODEL_NAME}), strategy={args.strategy}, "
        f"indexing {len(docs)} document(s) — first run may take ~15-30s per large doc…",
        flush=True,
    )
    started = time.time()
    all_records: List[ChunkRecord] = []
    parse_info: Dict[str, dict] = {}
    for d in docs:
        print(f"ingest: processing {d.doc_id} ({args.strategy}) …", flush=True)
        pages = parse_pdf(d.path)
        if args.strategy == "clause":
            recs = segment_pages(
                pages, doc_id=d.doc_id, doc_title=d.title, framework=d.framework,
                version=d.version, circular_ref=d.circular_ref, model_tag=model_tag,
            )
        else:
            recs = chunk_pages(
                pages, doc_id=d.doc_id, doc_title=d.title, framework=d.framework,
                version=d.version, circular_ref=d.circular_ref, model_tag=model_tag,
                chunk_words=args.chunk_words, overlap=args.overlap,
            )
        all_records.extend(recs)
        parse_info[d.doc_id] = {
            "d": d, "pages": len(pages), "chars": extracted_char_count(pages)
        }

    scope_cards: List[ChunkRecord] = []
    if args.strategy == "clause":
        scope_cards = build_scope_cards(all_records, model_tag)
        all_records.extend(scope_cards)
        print(f"ingest: generated {len(scope_cards)} scope card(s)", flush=True)

    by_doc: Dict[str, List[ChunkRecord]] = defaultdict(list)
    for r in all_records:
        by_doc[r.doc_id].append(r)

    total_added = total_stale = 0
    for doc_id, recs in by_doc.items():
        added, stale = _sync_doc(col, doc_id, recs)
        total_added += added
        total_stale += stale

    total_pages = sum(v["pages"] for v in parse_info.values())
    total_chunks = len(all_records)
    per_doc = []
    for doc_id, recs in by_doc.items():
        info = parse_info.get(doc_id)
        d: ManifestDoc = info["d"] if info else None
        per_doc.append({
            "doc_id": doc_id,
            "title": d.title if d else "",
            "framework": d.framework if d else "",
            "version": d.version if d else "",
            "chunk_count": len(recs),
            "scope_cards": sum(1 for r in recs if r.chunk_type == "scope_card"),
            "has_text_layer": d.has_text_layer if d else None,
            "source_sha256": d.source_sha256 if d else "",
            "pages": info["pages"] if info else 0,
        })

    elapsed = time.time() - started
    iv = _write_index_info(col, args, model_tag, per_doc, elapsed, total_pages, total_chunks, args.strategy)
    changed = total_added > 0 or total_stale > 0
    print(
        f"ingest: done in {elapsed:.1f}s — {total_chunks} chunks ({len(scope_cards)} scope cards) "
        f"across {len(docs)} docs; collection holds {col.count()}. "
        + ("CHANGED" if changed else "no changes (idempotent)")
    )
    print(f"ingest: index_version={iv}")
    return 0


def _run_reembed(args, col, model_tag) -> int:
    data = col.get(include=["documents", "metadatas"])
    ids, texts, metas = data["ids"], data["documents"], data["metadatas"]
    if not ids:
        print("ingest: nothing to re-embed (empty collection)", file=sys.stderr)
        return 1
    print(f"ingest: re-embedding {len(ids)} chunks under model_tag={model_tag} (no re-parse)…", flush=True)
    started = time.time()

    new_records: List[ChunkRecord] = []
    for cid, text, meta in zip(ids, texts, metas):
        m = store.decode_metadata(meta)
        new_id = chunk_id(m.get("doc_id", ""), m.get("clause_id", ""), text, model_tag)
        new_records.append(ChunkRecord(
            chunk_id=new_id, text=text, doc_id=m.get("doc_id", ""), doc_title=m.get("doc_title", ""),
            framework=m.get("framework", ""), clause_id=m.get("clause_id", ""),
            heading_path=m.get("heading_path", []), chunk_type=m.get("chunk_type", "clause"),
            entity_types=m.get("entity_types", []), product_types=m.get("product_types", []),
            version=m.get("version", ""), circular_ref=m.get("circular_ref", ""),
            page=m.get("page", 0), model_tag=model_tag,
            source_clause_chunk_id=m.get("source_clause_chunk_id"),
        ))
    _upsert_batched(col, new_records)
    new_ids = {r.chunk_id for r in new_records}
    stale = [i for i in ids if i not in new_ids]
    if stale:
        col.delete(ids=stale)
    elapsed = time.time() - started
    strategy = (store.read_index_info() or {}).get("chunking_strategy", "clause")
    per_doc = []
    for doc_id in sorted({r.doc_id for r in new_records}):
        per_doc.append({"doc_id": doc_id, "chunk_count": len(col.get(where={"doc_id": doc_id}, include=[])["ids"])})
    iv = _write_index_info(col, args, model_tag, per_doc, elapsed, 0, len(new_records), strategy)
    print(
        f"ingest: re-embedded {len(new_records)} chunks in {elapsed:.1f}s; "
        f"{len(stale)} old-tag chunks removed; collection holds {col.count()}."
    )
    print(f"ingest: index_version={iv}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="orcas-ingest", description="ORCAS corpus ingest")
    p.add_argument("--corpus", default=None)
    p.add_argument("--chroma-dir", default=None)
    p.add_argument("--collection", default=DEFAULT_COLLECTION)
    p.add_argument("--index-info", default=None)
    p.add_argument("--strategy", choices=["clause", "fixed"], default="clause")
    p.add_argument("--chunk-words", type=int, default=180, help="fixed strategy window size")
    p.add_argument("--overlap", type=int, default=40, help="fixed strategy overlap")
    p.add_argument("--reindex-if-changed", action="store_true",
                   help="idempotent full pass (upsert-by-id is already a no-op when unchanged)")
    p.add_argument("--re-embed", action="store_true",
                   help="re-embed stored chunks under --model-tag, by id, without re-parsing")
    p.add_argument("--model-tag", default=None)
    return p


def main(argv=None) -> int:
    return run(build_parser().parse_args(argv))
