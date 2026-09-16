"""Planar 랜드마크 선택법과 ALT 휴리스틱 admissibility 검증."""

import math

import networkx as nx
import pytest

from src.route_engine.landmark_planar import select_landmarks_planar
from src.route_engine.landmark_shared import (
    alt_heuristic,
    precompute_landmark_distances,
    verify_admissible,
)

_BASE_LAT, _BASE_LON = 37.50, 127.00


def _grid_graph(rows=5, cols=5, edge_length=100.0):
    """좌표 간격을 length보다 훨씬 작게 잡아(수 미터 이내) Haversine admissibility
    전제를 만족하는 toy 그래프 — route_engine/README.md의 admissibility 전제 절 참고."""
    G = nx.Graph()
    for r in range(rows):
        for c in range(cols):
            node = r * cols + c
            G.add_node(node, lat=_BASE_LAT + r * 0.00005, lon=_BASE_LON + c * 0.00005)
    for r in range(rows):
        for c in range(cols):
            node = r * cols + c
            if c + 1 < cols:
                G.add_edge(node, node + 1, length=edge_length)
            if r + 1 < rows:
                G.add_edge(node, node + cols, length=edge_length)
    return G


def _radial_graph(n_sectors=8):
    """중심 노드 1개 + 각 섹터 '중앙' 각도에 정확히 놓인 외곽 노드. 섹터 경계
    (예: 45도 간격의 배수)에 노드를 두면 atan2/radians 변환의 부동소수 반올림
    때문에 floor()가 인접 섹터로 흔들릴 수 있어, 경계에서 절반만큼 띄운 각도를
    쓴다."""
    G = nx.Graph()
    G.add_node("center", lat=_BASE_LAT, lon=_BASE_LON)
    lat0_rad = math.radians(_BASE_LAT)
    sector_width_deg = 360 / n_sectors
    outer = {}
    for i in range(n_sectors):
        deg = i * sector_width_deg + sector_width_deg / 2
        rad = math.radians(deg)
        dlat = 0.00045 * math.cos(rad)
        dlon = (0.00045 * math.sin(rad)) / math.cos(lat0_rad)
        node = f"n{i}"
        G.add_node(node, lat=_BASE_LAT + dlat, lon=_BASE_LON + dlon)
        outer[i] = node
        G.add_edge("center", node, length=200.0)
    keys = list(outer)
    for i in range(len(keys)):
        G.add_edge(outer[keys[i]], outer[keys[(i + 1) % len(keys)]], length=200.0)
    return G, outer


def test_planar_selects_one_landmark_per_45_degree_sector():
    G, outer = _radial_graph()
    landmarks = select_landmarks_planar(G, 8)
    assert set(landmarks) == set(outer.values())
    assert "center" not in landmarks


def test_planar_can_return_fewer_than_n_sectors_when_sectors_are_empty():
    # 모든 노드가 좁은 각도 범위(북동쪽)에 몰려 있으면 상당수 섹터가 비어야 한다.
    G = nx.Graph()
    G.add_node("center", lat=_BASE_LAT, lon=_BASE_LON)
    for i in range(5):
        node = f"ne{i}"
        G.add_node(node, lat=_BASE_LAT + 0.0002 + i * 0.00001, lon=_BASE_LON + 0.0002)
        G.add_edge("center", node, length=200.0)
    landmarks = select_landmarks_planar(G, 16)
    assert 0 < len(landmarks) < 16


def test_planar_rejects_invalid_n_sectors():
    G = _grid_graph(rows=2, cols=2)
    with pytest.raises(ValueError):
        select_landmarks_planar(G, 0)


def test_planar_landmarks_give_admissible_alt_heuristic():
    G = _grid_graph()
    landmarks = select_landmarks_planar(G, 8)
    table = precompute_landmark_distances(G, landmarks, weight="length")
    nodes = list(G.nodes)
    pairs = [(nodes[i], nodes[j]) for i in range(len(nodes)) for j in range(i + 1, len(nodes))]

    report = verify_admissible(G, table, weight="length", pairs=pairs)

    assert report.alt_violations == 0
    assert report.haversine_violations == 0
    assert report.checked_pairs == len(pairs)


def test_alt_heuristic_matches_triangle_inequality_by_hand():
    table = {"L": {0: 10.0, 1: 25.0}}
    assert alt_heuristic(table, 0, 1) == pytest.approx(15.0)
    assert alt_heuristic(table, 1, 0) == pytest.approx(15.0)
