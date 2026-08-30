"""Planar 랜드마크 선택법(Goldberg & Harrelson, 2005).

그래프 중심점(centroid) 기준으로 평면을 N개 섹터로 나누고, 섹터마다 중심에서
가장 먼 노드 1개를 랜드마크로 고른다. 공용 인프라(거리표·휴리스틱·admissibility
검증)는 landmark_shared.py를 그대로 쓴다.
"""

from __future__ import annotations

import math

import networkx as nx

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.landmark_shared import _largest_component_nodes


def _centroid(G: nx.Graph, nodes: list[int]) -> tuple[float, float]:
    """nodes의 (lat, lon) 산술평균. 서울 시내 규모에서는 구면 곡률로 인한
    오차가 무시할 만하다고 가정하며, 실측으로 검증하지는 않았다."""
    lats = [G.nodes[n]["lat"] for n in nodes]
    lons = [G.nodes[n]["lon"] for n in nodes]
    return sum(lats) / len(lats), sum(lons) / len(lons)


def select_landmarks_planar(G: nx.Graph, n_sectors: int) -> list[int]:
    """Planar 랜드마크 선택법.

    그래프 중심점(centroid)을 기준으로 평면을 n_sectors개 각도 섹터로 나누고,
    섹터마다 중심에서 Haversine 직선거리가 가장 먼 노드 1개를 랜드마크로 고른다.
    도로망 거리 계산(SSSP)이 전혀 필요 없어 Farthest 선택법보다 훨씬 저렴하다.

    각도는 dlat(북=0)를 x축, cos(centroid위도)로 보정한 dlon을 y축으로 삼은
    단순 등장방형(equirectangular) 근사로 계산한다 — 정북 기준 시계방향
    bearing과 동일한 값이 나오며, 서울 시내 규모에서 곡률 오차는 무시할
    만하다고 가정한다(실측 검증 안 함).

    노드가 없는 섹터는 랜드마크를 내지 않으므로, 반환 개수가 n_sectors보다
    적을 수 있다 — 버그가 아니라 좌표 분포에 따른 예상 동작이다.
    """
    if n_sectors < 1:
        raise ValueError("n_sectors는 1 이상이어야 합니다.")
    nodes = _largest_component_nodes(G)
    centroid_lat, centroid_lon = _centroid(G, nodes)
    lat0_rad = math.radians(centroid_lat)
    sector_width = 2 * math.pi / n_sectors

    best_by_sector: dict[int, tuple[float, int]] = {}
    for n in nodes:
        lat = G.nodes[n]["lat"]
        lon = G.nodes[n]["lon"]
        dlat = math.radians(lat - centroid_lat)
        dlon = math.radians(lon - centroid_lon) * math.cos(lat0_rad)
        angle = math.atan2(dlon, dlat) % (2 * math.pi)
        sector = int(angle // sector_width)
        dist = PathUtils._haversine_m(centroid_lat, centroid_lon, lat, lon)
        current = best_by_sector.get(sector)
        if current is None or dist > current[0]:
            best_by_sector[sector] = (dist, n)

    return [node for _, node in best_by_sector.values()]
