"""
tests/unit/test_waypoint_pool.py
WaypointPoolGenerator / WaypointPoolResult 단위 테스트

검증 항목:
  - r_max(target_m/2) 이내 노드만 풀에 포함되고, p1 자신은 제외됨
  - distance()가 lazy 계산으로 실제 최단거리와 일치함
  - 반대 방향 조회는 이미 캐시된 행을 재사용함(새로 계산하지 않음)
  - 캐시 행 수가 상한을 넘으면 LRU로 가장 오래된 행부터 제거됨
  - blocked_tags에 해당하는 edge는 차단되어 그 너머 노드가 후보에서 빠짐
  - 풀 노드가 아닌 값으로 조회하면 ValueError
  - p1 최근접 노드를 못 찾으면 None을 반환함
"""

import pytest
import networkx as nx

from src.route_engine.engines.waypoint_pool import WaypointPoolGenerator


@pytest.fixture
def line_graph():
    """
    일직선 그래프: 0 -- 1 -- 2 -- 3 -- 4 (각 edge length=100). p1=0.
    """
    G = nx.Graph()
    for i in range(5):
        G.add_node(i, lat=37.5 + i * 0.00001, lon=127.0 + i * 0.00001)
    for i in range(4):
        G.add_edge(i, i + 1, length=100, tags=[])
    return G


class TestBuildPool:
    def test_r_max_이내_노드만_포함된다(self, line_graph):
        gen = WaypointPoolGenerator(line_graph)
        result = gen.build_pool(37.5, 127.0, target_km=0.3)  # r_max=150m
        assert result.pool_nodes == [1]
        assert result.dist_from_p1 == {1: 100}

    def test_p1_자신은_풀에서_제외된다(self, line_graph):
        gen = WaypointPoolGenerator(line_graph)
        result = gen.build_pool(37.5, 127.0, target_km=1.0)  # r_max=500m -> 전체 포함
        assert 0 not in result.pool_nodes

    def test_p1_노드를_찾지_못하면_None을_반환한다(self):
        G = nx.Graph()
        G.add_node(0, lat=0.0, lon=0.0)  # 쿼리 좌표에서 R2(300m) 밖
        gen = WaypointPoolGenerator(G)
        assert gen.build_pool(37.5, 127.0, target_km=1.0) is None


class TestDistance:
    def test_lazy_계산이_최단거리와_일치한다(self, line_graph):
        gen = WaypointPoolGenerator(line_graph)
        result = gen.build_pool(37.5, 127.0, target_km=1.0)  # r_max=500m
        assert result.distance(1, 2) == 100
        assert result.distance(1, 4) == 300

    def test_반대_방향_조회는_캐시된_행을_재사용한다(self, line_graph):
        gen = WaypointPoolGenerator(line_graph)
        result = gen.build_pool(37.5, 127.0, target_km=1.0)
        assert result.distance(1, 4) == 300
        assert result.cached_row_count == 1
        assert result.distance(4, 1) == 300  # 반대 방향 — 새 행 계산 없이 기존 캐시 재사용
        assert result.cached_row_count == 1

    def test_캐시_행_수가_상한을_넘으면_LRU로_제거된다(self, line_graph):
        gen = WaypointPoolGenerator(line_graph)
        result = gen.build_pool(37.5, 127.0, target_km=1.0, pairwise_cache_rows=2)
        result.distance(1, 2)  # 행 1 캐시
        result.distance(2, 3)  # 행 2 캐시(총 2개, 상한 도달)
        result.distance(3, 4)  # 행 3 캐시 -> 가장 오래된 행 1 제거돼야 함
        assert result.cached_row_count == 2
        assert 1 not in result._row_cache
        assert 3 in result._row_cache

    def test_blocked_tags에_해당하는_edge는_차단된다(self, line_graph):
        line_graph[1][2]["tags"] = ["blocked"]
        gen = WaypointPoolGenerator(line_graph, blocked_tags=["blocked"])
        result = gen.build_pool(37.5, 127.0, target_km=1.0)
        assert result.pool_nodes == [1]  # 1-2가 막혀 2,3,4는 0에서 도달 불가

    def test_풀_노드가_아니면_ValueError를_던진다(self, line_graph):
        gen = WaypointPoolGenerator(line_graph)
        result = gen.build_pool(37.5, 127.0, target_km=1.0)
        with pytest.raises(ValueError):
            result.distance(0, 1)  # 0(p1)은 풀 노드가 아님
