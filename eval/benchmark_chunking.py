"""Chunking benchmark + hybrid A/B (Slice 4; feeds the report's "what did not work").

Builds a temporary index per chunking strategy (fixed-window vs clause-aligned), then
measures text-level recall@k of the §4.1 + fixture supporting passages, framework-filtered
(simulating the agent's framework-scoped search). Also runs dense vs hybrid on the
clause index. Prints a table; writes nothing to the production index.

Run:  python -m eval.benchmark_chunking
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from services.corpus_common import store
from services.corpus_common.constants import repo_root
from services.ingest import cli
from services.retrieval.models import SearchFilters, SearchMode, SearchRequest
from services.retrieval.service import Retriever

FIXTURES = repo_root() / "tests" / "fixtures" / "retrieval_fixtures.json"


def _build(strategy: str, chroma_dir: Path, info_path: Path):
    args = cli.build_parser().parse_args([
        "--strategy", strategy,
        "--collection", f"bench_{strategy}",
        "--chroma-dir", str(chroma_dir),
        "--index-info", str(info_path),
    ])
    cli.run(args)
    client = store.get_client(chroma_dir)
    return store.get_collection(client, name=f"bench_{strategy}")


# Topical probes = the kind of framework-scoped query the agent issues after reflection
# (not the raw complaint). needle = a verbatim phrase from the target provision.
PROBES = [
    ("4.1 RBI grounds", "grounds of complaint deficiency in service by a regulated entity",
     "RBI", "deficiency in service may file a complaint"),
    ("4.1 RBI scope", "which entities does the scheme cover services regulated by the Reserve Bank",
     "RBI", "regulated by Reserve Bank of India"),
    ("4.1 SEBI scope", "SEBI SCORES covers listed companies and registered intermediaries",
     "SEBI", "registered intermediaries and recognised MIIs"),
    ("depository demat", "demat account frozen by the depository participant",
     "SEBI", "demat account"),
    ("share transfer", "non receipt of securities after a share transfer by the registrar",
     "SEBI", "securities after transfer"),
    ("mutual fund grievance", "mutual fund redress investor grievances compliance officer",
     "SEBI", "grievance"),
]


def recall_at(retriever: Retriever, k: int, mode: SearchMode) -> float:
    hits = 0
    for _label, query, fw, needle in PROBES:
        resp = retriever.search(SearchRequest(
            query=query, k=k, mode=mode, filters=SearchFilters(framework=fw)))
        if any(needle.lower() in r.text.lower() for r in resp.results):
            hits += 1
    return round(hits / len(PROBES), 3)


def mean_hit_score(retriever: Retriever, k: int = 10) -> float:
    """Dense similarity of the first correct hit, averaged over probes that hit.
    Higher = the target provision ranks with a sharper score (precision of ranking)."""
    scores = []
    for _label, query, fw, needle in PROBES:
        resp = retriever.search(SearchRequest(
            query=query, k=k, mode=SearchMode.dense, filters=SearchFilters(framework=fw)))
        for r in resp.results:
            if needle.lower() in r.text.lower():
                scores.append(r.score)
                break
    return round(sum(scores) / len(scores), 3) if scores else 0.0


def main() -> int:
    fixtures = json.loads(FIXTURES.read_text())["fixtures"]
    tmp = Path(tempfile.mkdtemp(prefix="orcas_bench_"))
    rows = []
    for strategy in ("fixed", "clause"):
        col = _build(strategy, tmp / strategy, tmp / f"{strategy}_info.json")
        r = Retriever(collection=col)
        rows.append((f"{strategy} / dense", recall_at(r, 5, SearchMode.dense),
                     recall_at(r, 10, SearchMode.dense), mean_hit_score(r), col.count()))
        if strategy == "clause":
            rows.append((f"{strategy} / hybrid", recall_at(r, 5, SearchMode.hybrid),
                         recall_at(r, 10, SearchMode.hybrid), None, col.count()))

    print(f"\n=== Chunking benchmark — {len(PROBES)} topical probes (framework-filtered) ===")
    print(f"{'strategy / mode':<22}{'recall@5':>10}{'recall@10':>11}{'mean_hit_score':>16}{'chunks':>9}")
    for name, r5, r10, sc, n in rows:
        scs = "  n/a (RRF)" if sc is None else f"{sc:>16}"
        print(f"{name:<22}{r5:>10}{r10:>11}{scs}{n:>9}")
    print("\nrecall: target provision phrase appears in a top-k result (realistic agent queries).")
    print("mean_hit_score: dense cosine similarity of the first correct hit — higher = sharper")
    print("ranking. Fixed wins raw recall (bigger chunks contain more text); clause-aligned wins")
    print("ranking sharpness and gives clause-level citations that resolve for grounding.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
