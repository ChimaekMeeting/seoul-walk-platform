"""
tests/unit/test_graph_repository_scores.py
GraphRepository가 안전·편안 점수를 NetworkX edge로 전달하는지 검증 — #445 4단계

기존 tests/unit/test_graph_repository.py는 c5d8c13("링크 시설 플래그 제거",
2026-08-25) 이전의 넓은 계약(raw_is_* 플래그, is_walkable, tags, 8종 점수)을
assert하고 있어 그 커밋 이후 계속 실패 상태다. 그 계약을 되살릴지는 삭제를 결정한
쪽의 판단이므로 #445에서 건드리지 않고, 이 파일은 #445가 실제로 추가하는 세 점수만
검증한다.

검증 항목:
  - safety_score / accident_score / slope_score가 edge 속성으로 전달된다
  - NULL은 0.0으로 바뀌지 않고 None 그대로 전달된다(미계산과 0의 구분 보존)
  - 기존 속성(link_id, length)의 계약이 유지된다
  - 전달된 속성을 WeightedEdgeCost의 커버리지 게이트가 그대로 읽을 수 있다
"""

import importlib
import sys
from types import SimpleNamespace

import networkx as nx
import pytest

# conftest.py가 geoalchemy2 의존 때문에 이 모듈을 MagicMock으로 치환해 둔다.
# 실제 _edge_attributes를 검증해야 하므로 tests/unit/test_graph_repository.py와
# 같은 방식으로 원본 모듈을 다시 불러온다.
sys.modules.pop("src.repository.network.graph_repository", None)
GraphRepository = importlib.import_module(
    "src.repository.network.graph_repository"
).GraphRepository

from src.route_engine.scoring.scoring_engine import (
    ACCIDENT_ATTR,
    SAFETY_ATTR,
    SLOPE_ATTR,
    WeightedEdgeCost,
)

# ── 헬퍼 ────────────────────────────────────────────────────────────────────


def make_row(**overrides):
    """load_graph()의 select()가 돌려주는 row 모양."""
    values = {
        "link_id": 100,
        "start_node": 1,
        "end_node": 2,
        "length_m": 25.5,
        "safety_score": 0.7,
        "accident_score": 0.2,
        "slope_score": 0.5,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


# ── 점수 전달 ───────────────────────────────────────────────────────────────


def test_edge_attributes_pass_through_the_three_scores():
    attributes = GraphRepository._edge_attributes(make_row())

    assert attributes[SAFETY_ATTR] == 0.7
    assert attributes[ACCIDENT_ATTR] == 0.2
    assert attributes[SLOPE_ATTR] == 0.5


@pytest.mark.parametrize("attr", [SAFETY_ATTR, ACCIDENT_ATTR, SLOPE_ATTR])
def test_null_score_stays_none(attr):
    """NULL을 0.0으로 바꾸면 "미계산"과 "계산했고 0"을 영영 구분할 수 없게 된다."""
    attributes = GraphRepository._edge_attributes(make_row(**{attr: None}))

    assert attributes[attr] is None


def test_existing_edge_contract_is_unchanged():
    attributes = GraphRepository._edge_attributes(make_row())

    assert attributes["link_id"] == 100
    assert attributes["length"] == 25.5


# ── 커버리지 게이트와의 연결 ────────────────────────────────────────────────


def _graph_from_rows(rows) -> nx.Graph:
    G = nx.Graph()
    for row in rows:
        G.add_edge(
            row.start_node, row.end_node,
            **GraphRepository._edge_attributes(row),
        )
    return G


def test_fully_scored_graph_passes_the_coverage_gate():
    G = _graph_from_rows([make_row(link_id=i, start_node=i, end_node=i + 1) for i in range(10)])

    report = WeightedEdgeCost.check_coverage(G, min_ratio=0.9)

    assert report.ok is True
    assert report.ratios[SAFETY_ATTR] == pytest.approx(1.0)


def test_partially_scored_graph_is_reported_by_attribute():
    rows = [make_row(link_id=i, start_node=i, end_node=i + 1) for i in range(10)]
    for row in rows[:5]:
        row.accident_score = None

    report = WeightedEdgeCost.check_coverage(_graph_from_rows(rows), min_ratio=0.9)

    assert report.ok is False
    assert report.missing_attrs() == [ACCIDENT_ATTR]
    assert report.ratios[ACCIDENT_ATTR] == pytest.approx(0.5)
