"""
tests/unit/test_path_utils.py
PathUtils 단위 테스트

담당: QA (예원)
검증 항목:
  - find_nearest_node  : 가장 가까운 노드 탐색
  - extract_coordinates: 노드 ID → 좌표 변환
  - prune_dead_ends    : 왕복 가지 제거
  - remove_dead_ends   : degree=1 노드 반복 제거
  - calc_distance      : 총 이동 거리 계산
"""

import pytest
import networkx as nx

from src.route_engine.engines.path_utils import PathUtils

# ── 공통 픽스처 ──────────────────────────────────────────────────────────────


@pytest.fixture
def simple_graph():
    """
    노드 구성:
      0 (lat=37.5, lon=127.0)
      1 (lat=37.6, lon=127.1)
      2 (lat=37.7, lon=127.2)
    엣지: 0-1 (length=100), 1-2 (length=200)
    """
    G = nx.Graph()
    G.add_node(0, lat=37.5, lon=127.0)
    G.add_node(1, lat=37.6, lon=127.1)
    G.add_node(2, lat=37.7, lon=127.2)
    G.add_edge(0, 1, length=100, custom_score=1.0)
    G.add_edge(1, 2, length=200, custom_score=1.0)
    return G


@pytest.fixture
def utils(simple_graph):
    return PathUtils(simple_graph)


# ── find_nearest_node ────────────────────────────────────────────────────────


class TestFindNearestNode:
    def test_가장_가까운_노드를_반환한다(self, utils):
        # 노드 0 (37.5, 127.0) 바로 근처
        result = utils.find_nearest_node(37.50001, 127.00001)
        assert result == 0

    def test_노드_1에_가장_가까운_위치(self, utils):
        result = utils.find_nearest_node(37.60001, 127.10001)
        assert result == 1

    def test_빈_그래프에서는_None을_반환한다(self):
        G = nx.Graph()
        utils = PathUtils(G)
        assert utils.find_nearest_node(37.5, 127.0) is None

    def test_좌표_없는_노드는_스킵한다(self):
        G = nx.Graph()
        G.add_node(0)  # 좌표 없음
        G.add_node(1, lat=37.5, lon=127.0)  # 좌표 있음
        utils = PathUtils(G)
        result = utils.find_nearest_node(37.5, 127.0)
        assert result == 1

    def test_좌표_없는_노드만_있으면_None을_반환한다(self):
        G = nx.Graph()
        G.add_node(0)
        G.add_node(1)
        utils = PathUtils(G)
        assert utils.find_nearest_node(37.5, 127.0) is None


# ── extract_coordinates ──────────────────────────────────────────────────────


class TestExtractCoordinates:
    def test_노드_목록을_좌표로_변환한다(self, utils):
        result = utils.extract_coordinates([0, 1, 2])
        assert result == [[37.5, 127.0], [37.6, 127.1], [37.7, 127.2]]

    def test_그래프에_없는_노드는_스킵한다(self, utils):
        result = utils.extract_coordinates([0, 99, 2])
        assert result == [[37.5, 127.0], [37.7, 127.2]]

    def test_빈_목록은_빈_리스트를_반환한다(self, utils):
        assert utils.extract_coordinates([]) == []

    def test_좌표_없는_노드는_스킵한다(self, simple_graph):
        simple_graph.add_node(99)  # 좌표 없음
        utils = PathUtils(simple_graph)
        result = utils.extract_coordinates([0, 99])
        assert result == [[37.5, 127.0]]

    def test_반환_형식이_lat_lon_순서다(self, utils):
        result = utils.extract_coordinates([0])
        lat, lon = result[0]
        assert lat == 37.5
        assert lon == 127.0


# ── calc_distance ────────────────────────────────────────────────────────────


class TestCalcDistance:
    def test_두_노드_거리를_계산한다(self, utils):
        assert utils.calc_distance([0, 1]) == 100

    def test_세_노드_거리를_합산한다(self, utils):
        assert utils.calc_distance([0, 1, 2]) == 300

    def test_노드_하나면_0을_반환한다(self, utils):
        assert utils.calc_distance([0]) == 0

    def test_빈_목록이면_0을_반환한다(self, utils):
        assert utils.calc_distance([]) == 0

    def test_엣지에_length_없으면_0으로_처리한다(self):
        G = nx.Graph()
        G.add_node(0)
        G.add_node(1)
        G.add_edge(0, 1)  # length 속성 없음
        utils = PathUtils(G)
        assert utils.calc_distance([0, 1]) == 0


# ── remove_dead_ends ─────────────────────────────────────────────────────────


class TestRemoveDeadEnds:
    def test_degree_1_노드가_제거된다(self, utils):
        result = utils.remove_dead_ends()
        # 노드 0(연결: 1개), 노드 2(연결: 1개) 제거 → 노드 1만 남음
        assert 0 not in result.nodes
        assert 2 not in result.nodes
        assert 1 in result.nodes

    def test_원본_그래프는_수정되지_않는다(self, utils, simple_graph):
        original_count = simple_graph.number_of_nodes()
        utils.remove_dead_ends()
        assert simple_graph.number_of_nodes() == original_count

    def test_반환값은_새_그래프_객체다(self, utils, simple_graph):
        result = utils.remove_dead_ends()
        assert result is not simple_graph

    def test_사이클_그래프는_노드가_제거되지_않는다(self):
        G = nx.Graph()
        G.add_nodes_from([0, 1, 2])
        G.add_edges_from([(0, 1), (1, 2), (2, 0)])  # 삼각형 사이클
        utils = PathUtils(G)
        result = utils.remove_dead_ends()
        assert result.number_of_nodes() == 3

    def test_빈_그래프는_빈_그래프를_반환한다(self):
        utils = PathUtils(nx.Graph())
        result = utils.remove_dead_ends()
        assert result.number_of_nodes() == 0


# ── prune_dead_ends ──────────────────────────────────────────────────────────


class TestPruneDeadEnds:
    def test_왕복_구간을_제거한다(self, utils):
        # [0, 1, 0, 1, 2]: 0→1→0 왕복 구간(length=100) 제거 → [0, 1, 2]
        result = utils.prune_dead_ends([0, 1, 0, 1, 2])
        assert 0 not in result[1:-1]  # 중간에 0이 다시 나오지 않아야 함

    def test_왕복_없으면_그대로_반환한다(self, utils):
        path = [0, 1, 2]
        result = utils.prune_dead_ends(path)
        assert result == [0, 1, 2]

    def test_빈_리스트는_빈_리스트를_반환한다(self, utils):
        assert utils.prune_dead_ends([]) == []

    def test_max_branch_length_초과하면_제거하지_않는다(self):
        G = nx.Graph()
        G.add_nodes_from([0, 1, 2])
        G.add_edge(0, 1, length=500)  # 500m → max_branch_length(400) 초과
        G.add_edge(1, 0, length=500)
        G.add_edge(1, 2, length=100)
        utils = PathUtils(G)
        path = [0, 1, 0, 1, 2]
        result = utils.prune_dead_ends(path, max_branch_length=400.0)
        # 500m 구간은 제거 대상 아님
        assert len(result) == len(path)


# ── prune_dead_ends의 삭제 기록(sink) ────────────────────────────────────────
#
# "겹침 제거 로직을 겹침 기준으로 바꿀지, 아예 뺄지"를 나중에 데이터로 판단하기 위한
# 순수 진단 훅(2026-09-09). sink를 넘겨도 반환값은 달라지지 않아야 한다.


def _block_graph(edge_m: float = 50.0) -> nx.Graph:
    """4개 노드로 이루어진 블록 하나 + 곁가지. 엣지 길이를 실제 도보망 수준으로 짧게 둬
    블록 한 바퀴(4구간)가 max_branch_length(400m) 안에 들어오게 한다."""
    G = nx.Graph()
    for a, b in ((0, 1), (1, 2), (2, 3), (3, 0), (1, 9)):
        G.add_edge(a, b, length=edge_m)
    return G


class TestPruneDeadEndsSink:
    def test_sink를_넘겨도_반환값이_같다(self):
        utils = PathUtils(_block_graph())
        path = [0, 1, 9, 1, 2]
        sink = []
        assert utils.prune_dead_ends(path, sink=sink) == utils.prune_dead_ends(path)
        assert sink  # 기록은 남아야 한다

    def test_순수_왕복은_재통행률_0_5로_기록된다(self):
        utils = PathUtils(_block_graph())
        sink = []
        utils.prune_dead_ends([0, 1, 9, 1, 2], sink=sink)
        assert len(sink) == 1
        branch = sink[0]
        assert branch.anchor == 1
        assert branch.overlap_ratio == pytest.approx(0.5)  # 같은 엣지를 두 번 통행
        assert branch.length_m == pytest.approx(100.0)
        assert branch.interior == (9,)  # 이 제거로 경로에서 빠지는 노드

    def test_겹침_없는_블록_순환도_지워지며_재통행률_0으로_기록된다(self):
        """현재 규칙이 되짚어 온 길과 한 바퀴 돌아온 길을 구분하지 못한다는 사실 자체를
        고정한다 — 겹침 기준으로 바꾸면 살아남아야 할 구간이다."""
        utils = PathUtils(_block_graph())
        sink = []
        result = utils.prune_dead_ends([0, 1, 2, 3, 0], sink=sink)
        assert result == [0]  # 겹치는 엣지가 하나도 없는데 통째로 삭제된다
        assert len(sink) == 1
        assert sink[0].overlap_ratio == 0.0
        assert sink[0].length_m == pytest.approx(200.0)

    def test_sink를_안_넘기면_아무것도_기록하지_않는다(self):
        utils = PathUtils(_block_graph())
        # sink 기본값 None에서 예외 없이 기존 경로로 동작하는지만 확인한다.
        assert utils.prune_dead_ends([0, 1, 9, 1, 2]) == [0, 1, 2]
