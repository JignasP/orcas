"""Read corpus/MANIFEST.yaml and yield the documents to index."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

import yaml

from services.corpus_common.constants import repo_root


@dataclass
class ManifestDoc:
    doc_id: str
    title: str
    framework: str
    version: str
    circular_ref: str
    path: Path
    has_text_layer: bool
    source_sha256: str
    status: str


def load_manifest(corpus_dir: str | Path | None = None) -> List[ManifestDoc]:
    corpus_dir = Path(corpus_dir) if corpus_dir else repo_root() / "corpus"
    manifest_path = corpus_dir / "MANIFEST.yaml"
    data = yaml.safe_load(manifest_path.read_text())
    docs: List[ManifestDoc] = []
    for d in data.get("documents", []):
        file_rel = d.get("file", "")
        path = (corpus_dir / Path(file_rel).name) if file_rel else corpus_dir
        # file paths in the manifest are repo-relative to corpus/ (e.g. raw/x.pdf)
        if file_rel:
            path = corpus_dir / file_rel
        docs.append(
            ManifestDoc(
                doc_id=d["doc_id"],
                title=d.get("title", ""),
                framework=d.get("framework", ""),
                version=d.get("version", "") or "",
                circular_ref=d.get("circular_no", "") or d.get("title", ""),
                path=path,
                has_text_layer=bool(d.get("has_text_layer")),
                source_sha256=d.get("sha256", "") or "",
                status=d.get("status", ""),
            )
        )
    return docs


def indexable(docs: List[ManifestDoc]) -> List[ManifestDoc]:
    return [d for d in docs if d.status == "indexed_ready" and d.path.exists()]
