"""Re-embed flow: same model_tag re-embeds by id, in place — count and ids stable (D2/L1)."""
from services.corpus_common import store
from services.corpus_common.embedding import embed_texts
from services.corpus_common.ids import chunk_id
from services.corpus_common.store import ChunkRecord
from services.ingest import cli


def _seed(tmp):
    client = store.get_client(tmp)
    col = store.get_collection(client, name="reembed_test")
    recs = [
        ChunkRecord(chunk_id=chunk_id("d", f"c{i}", t, "minilm-l6-v2"), text=t, doc_id="d",
                    doc_title="D", framework="RBI", clause_id=f"c{i}", model_tag="minilm-l6-v2")
        for i, t in enumerate(["grounds of complaint deficiency in service",
                               "entities regulated by the Reserve Bank",
                               "mutual fund redemption and NAV"])
    ]
    col.upsert(ids=[r.chunk_id for r in recs], embeddings=embed_texts([r.text for r in recs]),
               documents=[r.text for r in recs], metadatas=[r.to_metadata() for r in recs])
    return col, [r.chunk_id for r in recs]


def test_reembed_same_tag_is_in_place(tmp_path):
    col, ids_before = _seed(str(tmp_path / "chroma"))
    assert col.count() == 3

    args = cli.build_parser().parse_args([
        "--re-embed", "--collection", "reembed_test", "--model-tag", "minilm-l6-v2",
        "--chroma-dir", str(tmp_path / "chroma"), "--index-info", str(tmp_path / "info.json"),
    ])
    assert cli.run(args) == 0

    col2 = store.get_collection(store.get_client(str(tmp_path / "chroma")), name="reembed_test")
    assert col2.count() == 3  # no full rebuild, no duplicates
    assert set(col2.get(include=[])["ids"]) == set(ids_before)  # same tag -> same ids
