from __future__ import annotations

import hashlib
import json
import os
import pickle
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import networkx as nx


class GraphArtifactError(RuntimeError):
    """배포용 Graph artifact가 없거나 계약과 다를 때 발생합니다."""


class GraphArtifactRepository:
    SCHEMA_VERSION = 1
    REQUIRED_NODE_ATTRIBUTES = frozenset({"lon", "lat"})
    REQUIRED_EDGE_ATTRIBUTES = frozenset(
        {"link_id", "length", "toilet_count", "transit_count", "accessibility_poi_count"}
    )

    @staticmethod
    def companion_paths(artifact_path: str | Path) -> tuple[Path, Path, Path]:
        artifact = Path(artifact_path)
        if artifact.suffix != ".pkl":
            raise GraphArtifactError("Graph artifact 확장자는 .pkl이어야 합니다.")
        base_name = artifact.name.removesuffix(".pkl")
        return (
            artifact,
            artifact.with_name(f"{base_name}.manifest.json"),
            artifact.with_name(f"{base_name}.sha256"),
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @classmethod
    def _validate_graph(cls, graph: nx.Graph) -> None:
        if not isinstance(graph, nx.Graph) or graph.is_directed() or graph.is_multigraph():
            raise GraphArtifactError("artifact는 무방향 단순 NetworkX Graph여야 합니다.")
        if graph.number_of_nodes() == 0 or graph.number_of_edges() == 0:
            raise GraphArtifactError("빈 Graph는 배포 artifact로 저장할 수 없습니다.")

        for node_id, attributes in graph.nodes(data=True):
            missing = cls.REQUIRED_NODE_ATTRIBUTES.difference(attributes)
            if missing:
                raise GraphArtifactError(
                    f"노드 {node_id}의 필수 속성이 없습니다: {sorted(missing)}"
                )

        for start, end, attributes in graph.edges(data=True):
            missing = cls.REQUIRED_EDGE_ATTRIBUTES.difference(attributes)
            if missing:
                raise GraphArtifactError(
                    f"엣지 ({start}, {end})의 필수 속성이 없습니다: {sorted(missing)}"
                )

    @staticmethod
    def _runtime_version_matches(built: str, current: str) -> bool:
        return built.split(".")[:2] == current.split(".")[:2]

    @classmethod
    def save(
        cls,
        graph: nx.Graph,
        artifact_path: str | Path,
        *,
        data_version: str,
        source_commit: str,
        source_dirty: bool,
    ) -> dict[str, Any]:
        cls._validate_graph(graph)
        artifact, manifest_path, checksum_path = cls.companion_paths(artifact_path)
        artifact.parent.mkdir(parents=True, exist_ok=True)

        artifact_tmp = artifact.with_name(f".{artifact.name}.tmp")
        manifest_tmp = manifest_path.with_name(f".{manifest_path.name}.tmp")
        checksum_tmp = checksum_path.with_name(f".{checksum_path.name}.tmp")

        try:
            with artifact_tmp.open("wb") as file:
                pickle.dump(graph, file, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(artifact_tmp, artifact)

            artifact_sha256 = cls._sha256(artifact)
            manifest = {
                "artifact_schema_version": cls.SCHEMA_VERSION,
                "artifact_file": artifact.name,
                "artifact_sha256": artifact_sha256,
                "artifact_size_bytes": artifact.stat().st_size,
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "data_version": data_version,
                "source_commit": source_commit,
                "source_dirty": source_dirty,
                "python_version": platform.python_version(),
                "networkx_version": nx.__version__,
                "graph_type": type(graph).__name__,
                "node_count": graph.number_of_nodes(),
                "edge_count": graph.number_of_edges(),
            }

            manifest_tmp.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(manifest_tmp, manifest_path)

            checksum_tmp.write_text(
                f"{artifact_sha256}  {artifact.name}\n",
                encoding="utf-8",
            )
            os.replace(checksum_tmp, checksum_path)
            return manifest
        finally:
            for temporary in (artifact_tmp, manifest_tmp, checksum_tmp):
                temporary.unlink(missing_ok=True)

    @classmethod
    def load(
        cls,
        artifact_path: str | Path,
        *,
        allow_dirty: bool = False,
        expected_data_version: str | None = None,
        expected_source_commit: str | None = None,
    ) -> nx.Graph:
        artifact, manifest_path, checksum_path = cls.companion_paths(artifact_path)
        for path in (artifact, manifest_path, checksum_path):
            if not path.is_file():
                raise GraphArtifactError(f"Graph artifact 구성 파일이 없습니다: {path}")

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GraphArtifactError(f"manifest를 읽을 수 없습니다: {exc}") from exc

        if manifest.get("artifact_schema_version") != cls.SCHEMA_VERSION:
            raise GraphArtifactError(
                "지원하지 않는 Graph artifact schema입니다: "
                f"{manifest.get('artifact_schema_version')}"
            )
        if manifest.get("source_dirty") and not allow_dirty:
            raise GraphArtifactError("미커밋 코드에서 생성된 artifact는 배포할 수 없습니다.")
        if (
            expected_data_version
            and manifest.get("data_version") != expected_data_version
        ):
            raise GraphArtifactError(
                "Graph 데이터 버전이 다릅니다: "
                f"expected={expected_data_version}, "
                f"actual={manifest.get('data_version')}"
            )
        if (
            expected_source_commit
            and manifest.get("source_commit") != expected_source_commit
        ):
            raise GraphArtifactError(
                "Graph 생성 커밋이 다릅니다: "
                f"expected={expected_source_commit}, "
                f"actual={manifest.get('source_commit')}"
            )
        if not cls._runtime_version_matches(
            str(manifest.get("python_version", "")),
            platform.python_version(),
        ):
            raise GraphArtifactError("artifact와 실행 환경의 Python major/minor가 다릅니다.")
        if not cls._runtime_version_matches(
            str(manifest.get("networkx_version", "")),
            nx.__version__,
        ):
            raise GraphArtifactError("artifact와 실행 환경의 NetworkX major/minor가 다릅니다.")

        artifact_sha256 = cls._sha256(artifact)
        checksum_parts = checksum_path.read_text(encoding="utf-8").split()
        if not checksum_parts:
            raise GraphArtifactError("checksum 파일이 비어 있습니다.")
        checksum_sha256 = checksum_parts[0]
        if artifact_sha256 != manifest.get("artifact_sha256"):
            raise GraphArtifactError("artifact SHA-256이 manifest와 다릅니다.")
        if artifact_sha256 != checksum_sha256:
            raise GraphArtifactError("artifact SHA-256이 checksum 파일과 다릅니다.")

        try:
            with artifact.open("rb") as file:
                graph = pickle.load(file)
        except (OSError, pickle.PickleError, EOFError) as exc:
            raise GraphArtifactError(f"Graph artifact를 읽을 수 없습니다: {exc}") from exc

        cls._validate_graph(graph)
        if graph.number_of_nodes() != manifest.get("node_count"):
            raise GraphArtifactError("Graph 노드 수가 manifest와 다릅니다.")
        if graph.number_of_edges() != manifest.get("edge_count"):
            raise GraphArtifactError("Graph 엣지 수가 manifest와 다릅니다.")
        return graph
