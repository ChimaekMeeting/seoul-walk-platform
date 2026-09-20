"""
tests/unit/test_waypoint_pool.py
WaypointPoolGenerator / WaypointPoolResult 단위 테스트

검증 항목:
  - r_max(target_m/2) 이내 노드만 풀에 포함되고, p1 자신은 제외됨
  - distance()가 lazy 계산으로 실제 최단거리와 일치함
  - 반대 방향 조회는 이미 캐시된 행을 재사용함(새로 계산하지 않음)
  - 캐시 행 수가 상한을 넘으면 LRU로 가장 오래된 행부터 제거됨
  - 풀 노드가 아닌 값으로 조회하면 ValueError
  - p1 최근접 노드를 못 찾으면 None을 반환함

build_pool_two_point (편도) 추가 검증 항목:
  - dist(p1,v)+dist(v,p2) <= budget_m인 노드만 포함되고, p1·p2 자신은 제외됨
  - target_km이 dist(p1,p2)보다 짧으면(물리적으로 불가능) target_m을 dist(p1,p2)로
    보정하고 계속 진행함(None을 반환하지 않음)
  - slack_ratio(기본 5%, dist(p1,p2) 대비 비율)가 클수록 더 넓은 노드까지 포함함
  - p1·p2 사이에 경로 자체가 없으면(그래프가 끊어짐) None을 반환함
  - distance()가 상속받은 lazy+LRU 캐시 그대로 동작함
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

    def test_풀_노드가_아니면_ValueError를_던진다(self, line_graph):
        gen = WaypointPoolGenerator(line_graph)
        result = gen.build_pool(37.5, 127.0, target_km=1.0)
        with pytest.raises(ValueError):
            result.distance(0, 1)  # 0(p1)은 풀 노드가 아님


class TestBuildPoolTwoPoint:
    """p1=0, p2=4, dist(p1,p2)=400m인 line_graph 기준."""

    def test_합_조건을_만족하는_노드만_포함되고_p1_p2는_제외된다(self, line_graph):
        gen = WaypointPoolGenerator(line_graph)
        # target_m=400 == dist(p1,p2) -> 모든 중간 노드가 정확히 경계에서 통과
        result = gen.build_pool_two_point(
            37.5, 127.0, 37.50004, 127.00004, target_km=0.4
        )
        assert sorted(result.pool_nodes) == [1, 2, 3]
        assert 0 not in result.pool_nodes
        assert 4 not in result.pool_nodes
        assert result.dist_from_p1 == {1: 100, 2: 200, 3: 300}
        assert result.dist_from_p2 == {1: 300, 2: 200, 3: 100}

    def test_target_km이_직선최단거리보다_짧으면_dist_p1p2로_보정한다(self, line_graph):
        gen = WaypointPoolGenerator(line_graph)
        # target_m=300 < dist(p1,p2)=400 -> target_m이 400으로 보정돼야 함(None 아님)
        result = gen.build_pool_two_point(
            37.5, 127.0, 37.50004, 127.00004, target_km=0.3
        )
        assert result is not None
        assert result.target_m == 400.0
        assert sorted(result.pool_nodes) == [1, 2, 3]

    def test_p1_또는_p2_노드를_찾지_못하면_None을_반환한다(self):
        G = nx.Graph()
        G.add_node(0, lat=0.0, lon=0.0)
        gen = WaypointPoolGenerator(G)
        assert gen.build_pool_two_point(37.5, 127.0, 37.6, 127.1, target_km=1.0) is None

    def test_p1_p2_사이에_경로가_없으면_None을_반환한다(self):
        """서로 다른 연결요소에 있는 두 점 — target_m 보정으로도 구할 수 없는 진짜 infeasible."""
        G = nx.Graph()
        G.add_node(0, lat=37.5, lon=127.0)
        G.add_node(1, lat=37.50001, lon=127.00001)
        G.add_edge(0, 1, length=50, tags=[])
        G.add_node(10, lat=38.0, lon=128.0)
        G.add_node(11, lat=38.00001, lon=128.00001)
        G.add_edge(10, 11, length=50, tags=[])
        gen = WaypointPoolGenerator(G)
        assert gen.build_pool_two_point(37.5, 127.0, 38.0, 128.0, target_km=100.0) is None

    def test_distance가_상속받은_lazy_캐시로_동작한다(self, line_graph):
        gen = WaypointPoolGenerator(line_graph)
        result = gen.build_pool_two_point(
            37.5, 127.0, 37.50004, 127.00004, target_km=0.4
        )
        assert result.distance(1, 3) == 200
        assert result.cached_row_count == 1
        assert result.distance(3, 1) == 200  # 반대 방향 — 캐시 재사용
        assert result.cached_row_count == 1


class TestBuildPoolTwoPointSlackRatio:
    """line_graph(0--1--2--3--4, dist(p1=0,p2=4)=400m)에 node2에서 60m 가지로 뻗은
    node5를 추가한 그래프. dist(0,5)+dist(5,4)=260+260=520m로, 직행 경로(0,4) 위에
    있지 않은 노드다.
    """

    @pytest.fixture
    def branching_graph(self, line_graph):
        line_graph.add_node(5, lat=37.6, lon=127.00002)
        line_graph.add_edge(2, 5, length=60, tags=[])
        return line_graph

    def test_기본_slack_ratio로는_직행경로_밖_노드가_제외된다(self, branching_graph):
        gen = WaypointPoolGenerator(branching_graph)
        # target_km=0.4 -> target_m=400(=dist(p1,p2), 보정 없음), 기본 slack_ratio=5%
        # -> budget_m=420 < node5의 520m
        result = gen.build_pool_two_point(
            37.5, 127.0, 37.50004, 127.00004, target_km=0.4
        )
        assert 5 not in result.pool_nodes

    def test_slack_ratio를_키우면_직행경로_밖_노드도_포함된다(self, branching_graph):
        gen = WaypointPoolGenerator(branching_graph)
        # slack_ratio=0.35 -> budget_m=400+140=540 >= node5의 520m
        result = gen.build_pool_two_point(
            37.5, 127.0, 37.50004, 127.00004, target_km=0.4, slack_ratio=0.35
        )
        assert 5 in result.pool_nodes
