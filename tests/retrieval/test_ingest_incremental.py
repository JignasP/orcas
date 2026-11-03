"""Ingest is incremental (D2): an unchanged corpus embeds nothing and keeps its index_version."""
import shutil

import pytest
import yaml

from services.corpus_common import store
from services.corpus_common.constants import repo_root
from services.ingest import cli

RBI = "rbi_integrated_ombudsman_scheme_2021"


@pytest.fixture()
def corpus(tmp_path):
    """A one-document corpus (the 18-page RBI scheme) so the test stays quick."""
    src = repo_root() / "corpus"
    doc = next(d for d in yaml.safe_load((src / "MANIFEST.yaml").read_text())["documents"]
               if d["doc_id"] == RBI)
    (tmp_path / "raw").mkdir()
    shutil.copy(src / doc["file"], tmp_path / doc["file"])
    (tmp_path / "MANIFEST.yaml").write_text(yaml.safe_dump({"documents": [doc]}))
    return tmp_path


def _ingest(corpus, tmp_path, *extra):
    args = cli.build_parser().parse_args([
        "--corpus", str(corpus), "--chroma-dir", str(tmp_path / "chroma"),
        "--index-info", str(tmp_path / "index_info.json"), "--collection", "ingest_incremental", *extra])
    assert cli.run(args) == 0
    return store.read_index_info(tmp_path / "index_info.json")


def test_second_run_embeds_nothing_and_keeps_the_index_version(corpus, tmp_path):
    first = _ingest(corpus, tmp_path)
    second = _ingest(corpus, tmp_path)
    assert first["throughput"]["embedded"] == first["chunk_count"] > 0
    assert second["throughput"]["embedded"] == 0
    assert second["index_version"] == first["index_version"]
    assert second["built_at"] >= first["built_at"]  # build time still recorded per run


def test_reembed_keeps_document_versions(corpus, tmp_path):
    first = _ingest(corpus, tmp_path)
    after = _ingest(corpus, tmp_path, "--re-embed")
    doc = next(d for d in after["documents"] if d["doc_id"] == RBI)
    assert doc["version"] and doc["source_sha256"] == first["documents"][0]["source_sha256"]
    assert after["index_version"] == first["index_version"]  # same model tag, same chunk ids
