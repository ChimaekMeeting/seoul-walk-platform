"""검증된 Graph artifact를 시각화 입력으로 읽는다."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import networkx as nx

from src.repository.network.graph_artifact_repository import GraphArtifactRepository


@dataclass(frozen=True)
class GraphSource:
    graph: nx.Graph
    artifact_path: Path
    manifest_path: Path
    checksum_path: Path
    manifest: dict[str, Any]


def load_graph_artifact(artifact_path: str | Path) -> GraphSource:
    """기존 저장소 로더의 무결성·버전 검사를 거쳐 도보망을 읽는다."""
    artifact = Path(artifact_path).expanduser().resolve()
    artifact, manifest_path, checksum_path = GraphArtifactRepository.companion_paths(artifact)
    graph = GraphArtifactRepository.load(artifact)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return GraphSource(
        graph=graph,
        artifact_path=artifact,
        manifest_path=manifest_path,
        checksum_path=checksum_path,
        manifest=manifest,
    )
