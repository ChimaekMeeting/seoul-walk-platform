"""ALT 런타임 준비(alt_runtime)의 폴백·부착·admissibility 검증.

실제 artifact(16만 노드)를 쓰지 않고 toy grid로만 돌린다. 핵심은 두 가지다.
"실패해도 서버 기동을 막지 않는가"와 "거리표가 deepcopy로 복제되지 않는가".
"""

import copy
import logging

import networkx as nx
import pytest

from src.route_engine.alt_runtime import (
    HEURISTIC_KEY,
    INFO_KEY,
    AltRuntimeInfo,
    attach_alt_heuristic,
    get_alt_heuristic,
    get_alt_info,
    prepare_alt_heuristic,
)
from src.route_engine.landmark_shared import (
    precompute_landmark_distances,
    verify_admissible,
)

_BASE_LAT, _BASE_LON = 37.50, 127.00
# 좌표 간격(도)을 간선 길이(m)보다 훨씬 작게 잡아 Haversine <= 도로거리를 보장한다.
_COORD_STEP = 0.00005
_EDGE_M = 100.0


def _grid(rows=6, cols=6):
    G = nx.Graph()
    for r in range(rows):
        for c in range(cols):
            node = r * cols + c
            G.add_node(
                node, lat=_BASE_LAT + r * _COORD_STEP, lon=_BASE_LON + c * _COORD_STEP
            )
    for r in range(rows):
        for c in range(cols):
            node = r * cols + c
            if c + 1 < cols:
                G.add_edge(node, node + 1, length=_EDGE_M)
            if r + 1 < rows:
                G.add_edge(node, node + cols, length=_EDGE_M)
    return G


# ────────────────────────────────────────────────
# 1. 비활성·미지원·실패 경로
# ────────────────────────────────────────────────


def test_disabled_returns_nothing_and_logs_once(caplog):
    G = _grid()
    with caplog.at_level(logging.INFO, logger="src.route_engine.alt_runtime"):
        heuristic, info = prepare_alt_heuristic(
            G, enabled=False, method="planar", k=8, seed=0
        )

    assert heuristic is None
    assert info is None
    assert len(caplog.records) == 1
    assert "WALK_ALT_ENABLED" in caplog.records[0].message


@pytest.mark.parametrize("method", ["farthest", "avoid", "", "PLANAR"])
def test_unsupported_method_raises_value_error(method):
    # 지원 여부는 이 함수 하나가 결정한다 — Farthest·Avoid는 의도적으로 빠져 있다.
    G = _grid()
    with pytest.raises(ValueError) as excinfo:
        prepare_alt_heuristic(G, enabled=True, method=method, k=8, seed=0)
    assert "지원하지 않는" in str(excinfo.value)


def test_selection_failure_falls_back_without_raising(caplog):
    # Planar는 노드의 lat/lon을 읽으므로 좌표가 없으면 KeyError가 난다.
    # 그래도 예외가 밖으로 나가면 안 된다(서버 기동을 막지 않는다).
    G = nx.Graph()
    G.add_edge(0, 1, length=_EDGE_M)

    with caplog.at_level(logging.WARNING, logger="src.route_engine.alt_runtime"):
        heuristic, info = prepare_alt_heuristic(
            G, enabled=True, method="planar", k=4, seed=0
        )

    assert heuristic is None
    assert info is None
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    # 예외 종류와 메시지가 로그에 남아야 원인을 찾을 수 있다.
    assert "KeyError" in warnings[0].message
    assert "폴백" in warnings[0].message


def test_empty_selection_falls_back(caplog, monkeypatch):
    G = _grid()
    monkeypatch.setattr(
        "src.route_engine.landmark_planar.select_landmarks_planar", lambda *a, **kw: []
    )

    with caplog.at_level(logging.WARNING, logger="src.route_engine.alt_runtime"):
        heuristic, info = prepare_alt_heuristic(
            G, enabled=True, method="planar", k=4, seed=0
        )

    assert heuristic is None
    assert info is None
    assert any("하나도 고르지 못했습니다" in r.message for r in caplog.records)


# ────────────────────────────────────────────────
# 2. 정상 준비
# ────────────────────────────────────────────────


def test_planar_preparation_reports_actual_landmark_count():
    G = _grid()
    heuristic, info = prepare_alt_heuristic(
        G, enabled=True, method="planar", k=4, seed=0
    )

    assert heuristic is not None
    assert isinstance(info, AltRuntimeInfo)
    assert info.method == "planar"
    assert info.k_requested == 4
    # Planar는 빈 섹터가 있으면 k보다 적게 낼 수 있어 실제 개수를 따로 담는다.
    assert info.k_actual == len(info.landmarks)
    assert 1 <= info.k_actual <= 4
    assert info.table_entries == info.k_actual * G.number_of_nodes()
    assert info.select_s >= 0.0
    assert info.table_s >= 0.0


def test_random_preparation_is_reproducible_for_the_same_seed():
    G = _grid()
    _, a = prepare_alt_heuristic(G, enabled=True, method="random", k=4, seed=7)
    _, b = prepare_alt_heuristic(G, enabled=True, method="random", k=4, seed=7)
    assert a.landmarks == b.landmarks


def test_prepared_heuristic_never_overestimates_real_distance():
    G = _grid()
    heuristic, info = prepare_alt_heuristic(
        G, enabled=True, method="planar", k=4, seed=0
    )

    # 같은 랜드마크로 만든 표를 verify_admissible에 넘겨 전체 쌍을 검사한다.
    table = precompute_landmark_distances(G, info.landmarks, weight="length")
    nodes = list(G.nodes)
    pairs = [(nodes[i], nodes[j]) for i in range(len(nodes)) for j in range(i + 1, len(nodes))]
    report = verify_admissible(G, table, weight="length", pairs=pairs)

    assert report.alt_violations == 0
    assert report.haversine_violations == 0
    assert report.checked_pairs == len(pairs)

    # 준비된 클로저 자체도 실제 최단거리를 넘지 않아야 한다.
    for u, v in pairs:
        assert heuristic(u, v) <= nx.shortest_path_length(G, u, v, weight="length") + 1e-6


# ────────────────────────────────────────────────
# 3. 그래프 부착과 deepcopy
# ────────────────────────────────────────────────


def test_attach_then_get_returns_the_same_callable():
    G = _grid()
    heuristic, info = prepare_alt_heuristic(
        G, enabled=True, method="planar", k=4, seed=0
    )
    attach_alt_heuristic(G, heuristic, info)

    assert get_alt_heuristic(G) is heuristic
    assert get_alt_info(G)["method"] == "planar"
    assert get_alt_info(G)["k_actual"] == info.k_actual


def test_attach_with_none_clears_a_previously_attached_heuristic():
    G = _grid()
    heuristic, info = prepare_alt_heuristic(
        G, enabled=True, method="planar", k=4, seed=0
    )
    attach_alt_heuristic(G, heuristic, info)
    attach_alt_heuristic(G, None, None)

    assert get_alt_heuristic(G) is None
    assert get_alt_info(G) is None
    assert HEURISTIC_KEY not in G.graph
    assert INFO_KEY not in G.graph


def test_get_alt_heuristic_is_none_on_a_bare_graph():
    assert get_alt_heuristic(_grid()) is None
    assert get_alt_info(_grid()) is None


def test_deepcopy_works_and_does_not_duplicate_the_distance_table():
    """visualizations/route_experiment.py가 실행마다 copy.deepcopy(graph)를 한다.

    거리표를 G.graph에 dict로 올리면 그 표까지 통째로 복제되므로, 표는 클로저 안에만
    두고 G.graph에는 함수 객체만 올린다. copy.deepcopy는 함수를 원자값으로 취급해
    그대로 돌려주므로 표가 복제되지 않는다.
    """
    G = _grid()
    heuristic, info = prepare_alt_heuristic(
        G, enabled=True, method="planar", k=4, seed=0
    )
    attach_alt_heuristic(G, heuristic, info)

    local = copy.deepcopy(G)

    assert local.graph[HEURISTIC_KEY] is G.graph[HEURISTIC_KEY]
    # 클로저가 잡은 거리표도 같은 객체여야 한다(복제되지 않았다는 뜻).
    cells = [cell.cell_contents for cell in (heuristic.__closure__ or ())]
    tables = [c for c in cells if isinstance(c, dict)]
    assert tables, "거리표를 잡은 클로저 셀을 찾지 못했습니다."
    copied_cells = [c.cell_contents for c in (local.graph[HEURISTIC_KEY].__closure__ or ())]
    for table in tables:
        assert any(c is table for c in copied_cells)

    # 복사본에서도 그대로 동작한다.
    assert local.graph[HEURISTIC_KEY](0, 35) == heuristic(0, 35)


def test_prepared_heuristic_exposes_the_landmark_table_and_survives_deepcopy():
    """시각화가 h(u,v)를 랜드마크별 항으로 분해하려면 같은 거리표를 읽어야 한다.

    표는 클로저 안에 있어 밖에서 꺼낼 수 없으므로 함수 객체 속성으로 붙인다.
    함수는 deepcopy에서 원자값이라 복사본도 같은 표 하나를 가리킨다.
    """
    G = _grid()
    heuristic, info = prepare_alt_heuristic(
        G, enabled=True, method="planar", k=4, seed=0
    )
    attach_alt_heuristic(G, heuristic, info)

    table = heuristic.landmark_table
    assert sorted(table) == sorted(info.landmarks)
    assert sum(len(row) for row in table.values()) == info.table_entries

    local = copy.deepcopy(G)
    assert local.graph[HEURISTIC_KEY].landmark_table is table
