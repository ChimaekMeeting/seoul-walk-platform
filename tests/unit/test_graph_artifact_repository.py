import json

import networkx as nx
import pytest

from src.repository.network.graph_artifact_repository import (
    GraphArtifactError,
    GraphArtifactRepository,
)


def make_graph() -> nx.Graph:
    graph = nx.Graph()
    node_attributes = {
        "node_type": "walk",
        "is_underground": False,
        "is_overpass": False,
    }
    graph.add_node(1, lon=126.9, lat=37.5, **node_attributes)
    graph.add_node(2, lon=126.91, lat=37.51, **node_attributes)
    graph.add_edge(
        1,
        2,
        link_id=10,
        length=100.0,
        raw_link_type_code="1010",
        is_walkable=True,
        safety_score=0.5,
        nature_score=0.4,
        slope_score=1.0,
        running_score=0.2,
        landmark_score=0.0,
        child_score=0.0,
        park_overlap_ratio=0.3,
        convenience_score=0.5,
        is_school_zone=False,
        is_vehicle_caution=False,
        toilet_count=1,
        transit_count=2,
        accessibility_poi_count=0,
        tags=[],
    )
    return graph


def save_graph(tmp_path, graph=None):
    artifact_path = tmp_path / "walk_graph_v1.pkl"
    manifest = GraphArtifactRepository.save(
        graph or make_graph(),
        artifact_path,
        data_version="test-v1",
        source_commit="abc123",
        source_dirty=False,
    )
    return artifact_path, manifest


def test_save_and_load_round_trip(tmp_path):
    artifact_path, manifest = save_graph(tmp_path)

    loaded = GraphArtifactRepository.load(artifact_path)

    assert loaded.number_of_nodes() == 2
    assert loaded.number_of_edges() == 1
    assert loaded[1][2]["park_overlap_ratio"] == 0.3
    assert manifest["data_version"] == "test-v1"
    assert manifest["source_commit"] == "abc123"
    assert manifest["source_dirty"] is False


def test_save_creates_manifest_and_checksum(tmp_path):
    artifact_path, manifest = save_graph(tmp_path)
    _, manifest_path, checksum_path = GraphArtifactRepository.companion_paths(
        artifact_path
    )

    saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checksum = checksum_path.read_text(encoding="utf-8").split()[0]

    assert saved_manifest == manifest
    assert checksum == manifest["artifact_sha256"]
    assert manifest["artifact_size_bytes"] == artifact_path.stat().st_size


def test_load_rejects_tampered_artifact(tmp_path):
    artifact_path, _ = save_graph(tmp_path)
    with artifact_path.open("ab") as file:
        file.write(b"tampered")

    with pytest.raises(GraphArtifactError, match="manifest"):
        GraphArtifactRepository.load(artifact_path)


def test_load_rejects_dirty_source_manifest(tmp_path):
    artifact_path, _ = save_graph(tmp_path)
    _, manifest_path, _ = GraphArtifactRepository.companion_paths(artifact_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_dirty"] = True
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(GraphArtifactError, match="미커밋"):
        GraphArtifactRepository.load(artifact_path)


def test_load_rejects_unexpected_data_version(tmp_path):
    artifact_path, _ = save_graph(tmp_path)

    with pytest.raises(GraphArtifactError, match="데이터 버전"):
        GraphArtifactRepository.load(
            artifact_path,
            expected_data_version="different-version",
        )


def test_load_rejects_unexpected_source_commit(tmp_path):
    artifact_path, _ = save_graph(tmp_path)

    with pytest.raises(GraphArtifactError, match="생성 커밋"):
        GraphArtifactRepository.load(
            artifact_path,
            expected_source_commit="different-commit",
        )


def test_save_rejects_missing_required_attributes(tmp_path):
    graph = make_graph()
    del graph[1][2]["safety_score"]

    with pytest.raises(GraphArtifactError, match="필수 속성"):
        save_graph(tmp_path, graph)


def test_companion_paths_require_pickle_extension(tmp_path):
    with pytest.raises(GraphArtifactError, match=".pkl"):
        GraphArtifactRepository.companion_paths(tmp_path / "walk_graph.json")
