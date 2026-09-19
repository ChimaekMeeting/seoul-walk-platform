"""
benchmarks/tests/test_graph_loader.py

benchmark.py::_load_default_graph()의 그래프 원본 계약을 고정한다(#474).

2026-09-20까지는 benchmarks/fixtures/*.parquet을 별도로 빌드해 읽었는데, 원본이 서비스가
읽는 artifact와 갈려 있어 조용히 드리프트했다(#473: fixture 160,328노드/223,927엣지 vs
artifact 160,197/223,693, accident_score 컬럼 자체가 누락). 이 테스트는 그 재발을 잡는다 —
"엣지에 SCORE_ATTRS 3종과 length·link_id가 있는가", "manifest의 노드/엣지 수와 일치하는가"만
확인하고, 그래프 자체의 지리적 내용은 검증하지 않는다.

artifact(artifacts/walk_graph_v1.pkl)는 .gitignore 대상이라 CI/새 클론에는 없을 수 있다 —
없으면 skip한다(_load_default_graph()가 None을 반환하는 것과 같은 완화 정책).
"""

import json

import pytest

from benchmarks import benchmark as bm
from benchmarks.config import WALK_GRAPH_ARTIFACT
from src.repository.network.graph_artifact_repository import GraphArtifactRepository
from src.route_engine.scoring.scoring_engine import SCORE_ATTRS, WeightedEdgeCost


def _manifest_or_skip() -> dict:
    artifact, manifest_path, _ = GraphArtifactRepository.companion_paths(WALK_GRAPH_ARTIFACT)
    if not artifact.is_file():
        pytest.skip(f"Graph artifact({artifact})가 없습니다 — 로컬/CI에 배포용 artifact 미준비")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def test_load_default_graph_matches_manifest_node_and_edge_count():
    manifest = _manifest_or_skip()

    graph = bm._load_default_graph()

    assert graph is not None
    assert graph.number_of_nodes() == manifest["node_count"]
    assert graph.number_of_edges() == manifest["edge_count"]


def test_load_default_graph_edges_carry_length_link_id_and_score_attrs():
    _manifest_or_skip()

    graph = bm._load_default_graph()

    _, _, sample = next(iter(graph.edges(data=True)))
    assert "length" in sample
    assert "link_id" in sample
    for attr in SCORE_ATTRS:
        assert attr in sample


def test_load_default_graph_passes_weighted_cost_coverage_gate():
    """#473이 고친 게 실제로 커버리지 게이트를 통과시키는지 — 회귀 재발 방지의 핵심 단언."""
    _manifest_or_skip()

    graph = bm._load_default_graph()

    report = WeightedEdgeCost.check_coverage(graph, min_ratio=0.95)
    assert report.ok, f"미달 속성={report.missing_attrs()}, 적재율={dict(report.ratios)}"


def test_load_default_graph_returns_none_without_raising_when_artifact_missing(
    tmp_path, monkeypatch,
):
    """artifact가 없는 환경(CI, 새 클론)에서도 예외 없이 None을 반환해 dummy 알고리즘만
    으로 하네스를 계속 쓸 수 있어야 한다."""
    monkeypatch.setattr(bm, "WALK_GRAPH_ARTIFACT", tmp_path / "no_such_walk_graph.pkl")

    assert bm._load_default_graph() is None
