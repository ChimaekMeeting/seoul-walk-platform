"""
tests/unit/test_path_utils.py
PathUtils 단위 테스트

담당: QA (예원)
검증 항목:
  - find_nearest_node  : 가장 가까운 노드 탐색
  - extract_coordinates: 노드 ID → 좌표 변환
  - prune_dead_ends    : 왕복 가지 제거, sink 진단 기록
  - remove_dead_ends   : degree=1 노드 반복 제거
  - calc_distance      : 총 이동 거리 계산
  - turn_angle / turn_angle_at / turn_angle_result / turn_angles / turn_metrics
                       : 방향 전환(회전각) 계산 — 열린/닫힌 경로, 정의 불가 케이스
  - path_distance_m    : 닫힌 경로 포함 총 이동 거리 계산
  - count_turns_at_or_above: 임계값 이상 회전 개수(분석용 헬퍼)
  - astar_path / _search_heuristic: 부착된 ALT 우선 사용, Haversine 폴백,
                       min_ratio < 1.0에서 ALT 제외(#465)
"""

import pytest
import networkx as nx

from src.route_engine.alt_runtime import (
    attach_alt_heuristic,
    get_alt_heuristic,
    prepare_alt_heuristic,
)
from src.route_engine.engines.path_utils import (
    PathUtils,
    latlon_to_local_xy,
    turn_angle,
    turn_angle_at,
    count_turns_at_or_above,
)

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


@pytest.fixture
def turn_graph():
    """
    방향 전환(turn_cost) 테스트용 그래프. 모든 이동을 순수 남북/동서 축으로만
    구성해, 등장방형 투영의 축별 축척 차이(cos(lat_ref) 보정)와 무관하게 0/90/180도가
    항상 정확히 나오도록 만들었다(축이 섞이면 축척 차이로 각도가 미세하게 어긋날 수 있음).

      A (37.500, 127.000)
      B (37.501, 127.000)  A 정북쪽(直進 기준점)
      C (37.502, 127.000)  B 정북쪽 → A→B→C 직선
      D (37.501, 127.001)  B 정동쪽 → A→B→D 좌/우 90도
      E (37.501, 126.999)  B 정서쪽 → A→B→E 반대 방향 90도
      X (37.503, 127.000)  좌표 없는 노드와 짝지어 missing_coordinate 테스트용
      DUP (=A와 동일 좌표, 다른 노드 id) → 0길이 벡터 테스트용
      NOCOORD: 좌표 속성 자체가 없는 노드

    엣지 length는 calc_distance/path_distance_m 테스트용으로 실제 거리와 무관하게
    구분 가능한 값을 부여했다.
    """
    G = nx.Graph()
    G.add_node("A", lat=37.500, lon=127.000)
    G.add_node("B", lat=37.501, lon=127.000)
    G.add_node("C", lat=37.502, lon=127.000)
    G.add_node("D", lat=37.501, lon=127.001)
    G.add_node("E", lat=37.501, lon=126.999)
    G.add_node("DUP", lat=37.500, lon=127.000)  # A와 좌표 동일
    G.add_node("NOCOORD")  # lat/lon 없음

    G.add_edge("A", "B", length=100.0)
    G.add_edge("B", "C", length=100.0)
    G.add_edge("B", "D", length=100.0)
    G.add_edge("B", "E", length=100.0)
    G.add_edge("A", "D", length=141.0)  # 삼각형 폐쇄 경로(A-B-D-A) 테스트용
    return G


@pytest.fixture
def turn_utils(turn_graph):
    return PathUtils(turn_graph)


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


# ── turn_angle (순수 함수) ───────────────────────────────────────────────────


class TestTurnAngle:
    def test_직선이면_0도(self):
        assert turn_angle((0, 0), (1, 0), (2, 0)) == pytest.approx(0.0)

    def test_좌회전_90도(self):
        assert turn_angle((0, 0), (1, 0), (1, 1)) == pytest.approx(90.0)

    def test_우회전_90도(self):
        assert turn_angle((0, 0), (1, 0), (1, -1)) == pytest.approx(90.0)

    def test_유턴이면_180도(self):
        assert turn_angle((0, 0), (1, 0), (0, 0)) == pytest.approx(180.0)

    def test_거의_직선인_부동소수점_입력도_0도에_가깝다(self):
        # acos clamp가 없으면 부동소수점 오차로 domain error가 날 수 있는 경계값
        result = turn_angle((0.0, 0.0), (1.0, 0.0), (2.0, 1e-12))
        assert result == pytest.approx(0.0, abs=1e-6)

    def test_직전과_현재가_같으면_None(self):
        assert turn_angle((1, 1), (1, 1), (2, 2)) is None

    def test_현재와_다음이_같으면_None(self):
        assert turn_angle((0, 0), (1, 0), (1, 0)) is None


# ── latlon_to_local_xy ───────────────────────────────────────────────────────


class TestLatlonToLocalXy:
    def test_위도가_커지면_y가_커진다(self):
        x1, y1 = latlon_to_local_xy(37.500, 127.000, lat_ref=37.500)
        x2, y2 = latlon_to_local_xy(37.501, 127.000, lat_ref=37.500)
        assert y2 > y1
        assert x1 == pytest.approx(x2)  # 경도가 같으면 x는 그대로

    def test_경도가_커지면_x가_커진다(self):
        x1, _ = latlon_to_local_xy(37.500, 127.000, lat_ref=37.500)
        x2, _ = latlon_to_local_xy(37.500, 127.001, lat_ref=37.500)
        assert x2 > x1


# ── turn_angle_at (그래프 래퍼) ──────────────────────────────────────────────


class TestTurnAngleAt:
    def test_남북_직진이면_0도(self, turn_graph):
        assert turn_angle_at(turn_graph, "A", "B", "C") == pytest.approx(0.0)

    def test_북쪽에서_동쪽으로_90도(self, turn_graph):
        assert turn_angle_at(turn_graph, "A", "B", "D") == pytest.approx(90.0)

    def test_북쪽에서_서쪽으로_90도(self, turn_graph):
        assert turn_angle_at(turn_graph, "A", "B", "E") == pytest.approx(90.0)

    def test_유턴이면_180도(self, turn_graph):
        assert turn_angle_at(turn_graph, "B", "A", "B") == pytest.approx(180.0)

    def test_좌표_없는_노드가_있으면_None(self, turn_graph):
        assert turn_angle_at(turn_graph, "A", "B", "NOCOORD") is None

    def test_동일_좌표로_인한_0길이_벡터면_None(self, turn_graph):
        # DUP은 A와 좌표가 동일 → curr(A)==next(DUP) 벡터 길이 0
        assert turn_angle_at(turn_graph, "B", "A", "DUP") is None


# ── count_turns_at_or_above ──────────────────────────────────────────────────


class TestCountTurnsAtOrAbove:
    def test_임계값_이상만_센다(self):
        angles = [10.0, 45.0, 60.0, 90.0, 120.0]
        assert count_turns_at_or_above(angles, 60.0) == 3

    def test_빈_목록이면_0(self):
        assert count_turns_at_or_above([], 45.0) == 0


# ── path_distance_m ──────────────────────────────────────────────────────────


class TestPathDistanceM:
    def test_열린_경로_거리(self, turn_utils):
        # A-B(100) + B-C(100)
        assert turn_utils.path_distance_m(["A", "B", "C"]) == pytest.approx(200.0)

    def test_닫힌_경로_시작노드_중복_없음(self, turn_utils):
        # A-B(100) + B-D(100) + D-A(141, 이음매)
        assert turn_utils.path_distance_m(["A", "B", "D"], closed=True) == pytest.approx(341.0)

    def test_닫힌_경로_시작노드_중복_있음_결과가_동일하다(self, turn_utils):
        no_dup = turn_utils.path_distance_m(["A", "B", "D"], closed=True)
        with_dup = turn_utils.path_distance_m(["A", "B", "D", "A"], closed=True)
        assert no_dup == pytest.approx(with_dup)

    def test_노드가_2개_미만이면_0(self, turn_utils):
        assert turn_utils.path_distance_m(["A"]) == 0.0
        assert turn_utils.path_distance_m([]) == 0.0


# ── turn_angle_result / turn_angles ──────────────────────────────────────────


class TestTurnAngleResult:
    def test_열린_경로는_양_끝_회전을_제외한다(self, turn_utils):
        # A-B-C: 회전이 정의되는 지점은 중간의 B뿐 — 양 끝(A, C)은 회전 계산 대상이 아님
        result = turn_utils.turn_angle_result(["A", "B", "C"])
        assert len(result.angles_deg) == 1  # B에서만 계산

    def test_빈_목록_한개_두개_노드는_회전이_없다(self, turn_utils):
        for path in ([], ["A"], ["A", "B"]):
            assert turn_utils.turn_angle_result(path).angles_deg == []

    def test_열린_왕복은_180도_하나를_반환한다(self, turn_utils):
        result = turn_utils.turn_angle_result(["A", "B", "A"])
        assert result.angles_deg == pytest.approx([180.0])

    def test_닫힌_경로_노드_2개는_회전이_없다(self, turn_utils):
        assert turn_utils.turn_angle_result(["A", "B"], closed=True).angles_deg == []

    def test_닫힌_경로_중복_제거후_서로다른_노드_2개는_회전이_없다(self, turn_utils):
        assert turn_utils.turn_angle_result(["A", "B", "A"], closed=True).angles_deg == []

    def test_닫힌_삼각형은_정확히_3개의_회전을_계산한다_중복없음(self, turn_utils):
        """폐쇄 경로 회전 누락 버그(메인 루프 + 이음매 패치 1개 방식이 n-1개만
        계산하던 문제)의 회귀 테스트 — 모듈러 순회로 n개 노드 모두의 회전을 계산한다."""
        result = turn_utils.turn_angle_result(["A", "B", "D"], closed=True)
        assert len(result.angles_deg) == 3

    def test_닫힌_삼각형은_정확히_3개의_회전을_계산한다_중복있음(self, turn_utils):
        result = turn_utils.turn_angle_result(["A", "B", "D", "A"], closed=True)
        assert len(result.angles_deg) == 3

    def test_시작노드_중복_유무와_무관하게_결과가_같다(self, turn_utils):
        no_dup = turn_utils.turn_angle_result(["A", "B", "D"], closed=True)
        with_dup = turn_utils.turn_angle_result(["A", "B", "D", "A"], closed=True)
        assert sorted(no_dup.angles_deg) == pytest.approx(sorted(with_dup.angles_deg))

    def test_좌표_누락_원인이_집계된다(self, turn_utils):
        result = turn_utils.turn_angle_result(["A", "B", "NOCOORD"])
        assert result.angles_deg == []
        assert result.undefined_reasons == {"missing_coordinate": 1}

    def test_내부_노드_재방문도_위치_기준으로_계산한다(self, turn_utils):
        # A-B-C-B-D: 재방문(B)이 있어도 위치 기준으로 각 지점의 회전을 그대로 계산
        result = turn_utils.turn_angle_result(["A", "B", "C", "B", "D"])
        assert len(result.angles_deg) == 3  # B, C, B 세 지점에서 계산(양 끝 A, D 제외)


class TestTurnAngles:
    def test_각도_리스트만_반환한다(self, turn_utils):
        angles = turn_utils.turn_angles(["A", "B", "D"], closed=True)
        assert isinstance(angles, list)
        assert max(angles, default=0.0) > 0  # 튜플이 아니라 리스트라 max()가 바로 동작


# ── turn_metrics ─────────────────────────────────────────────────────────────


class TestTurnMetrics:
    def test_닫힌_삼각형_통계(self, turn_utils):
        angles = turn_utils.turn_angles(["A", "B", "D"], closed=True)
        metrics = turn_utils.turn_metrics(["A", "B", "D"], closed=True)
        assert metrics.defined_turn_count == 3
        assert metrics.candidate_turn_count == 3
        assert metrics.undefined_turn_count == 0
        assert metrics.total_turn_deg == pytest.approx(sum(angles))
        assert metrics.max_turn_deg == pytest.approx(max(angles))
        assert metrics.turn_deg_per_km is not None

    def test_거리가_0이면_turn_deg_per_km은_None(self, turn_utils):
        # A만 있는 경로 → 거리 0, 회전도 없음
        metrics = turn_utils.turn_metrics(["A"])
        assert metrics.turn_deg_per_km is None

    def test_정의_불가_회전이_있으면_개수에_반영된다(self, turn_utils):
        metrics = turn_utils.turn_metrics(["A", "B", "NOCOORD"])
        assert metrics.defined_turn_count == 0
        assert metrics.undefined_turn_count == 1
        assert metrics.candidate_turn_count == 1
        assert metrics.undefined_turn_reasons == {"missing_coordinate": 1}


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


# ── astar_path 휴리스틱 선택(#465) ───────────────────────────────────────────
#
#   0 ── 1 ── 2 ── 3      직선
#   └──── 4 ── 5 ─┘       우회
#
# alt_runtime이 노드 ID를 int로 변환하므로 정수 ID를 쓴다.

_ALT_POS = {
    0: (37.5000, 127.0000),
    1: (37.5000, 127.0020),
    2: (37.5000, 127.0040),
    3: (37.5000, 127.0060),
    4: (37.5020, 127.0020),
    5: (37.5020, 127.0040),
}


def _alt_graph() -> nx.Graph:
    """length가 실제 Haversine 거리인 그래프 — Haversine과 ALT 둘 다 admissible한 조건."""
    G = nx.Graph()
    for node, (lat, lon) in _ALT_POS.items():
        G.add_node(node, lat=lat, lon=lon)
    for path in ([0, 1, 2, 3], [0, 4, 5, 3]):
        for u, v in zip(path, path[1:]):
            (lat1, lon1), (lat2, lon2) = _ALT_POS[u], _ALT_POS[v]
            G.add_edge(u, v, length=PathUtils._haversine_m(lat1, lon1, lat2, lon2))
    return G


def _attach_alt(G: nx.Graph):
    heuristic, info = prepare_alt_heuristic(G, enabled=True, method="planar", k=4, seed=0)
    attach_alt_heuristic(G, heuristic, info)
    return heuristic


class TestAstarHeuristicSelection:
    def test_ALT가_부착돼_있으면_그것을_쓴다(self):
        G = _alt_graph()
        attached = _attach_alt(G)
        assert attached is not None  # 부착 자체가 실패하면 이 테스트는 의미가 없다

        assert PathUtils(G)._search_heuristic(1.0) is attached

    def test_ALT가_없으면_Haversine으로_폴백한다(self):
        G = _alt_graph()
        assert get_alt_heuristic(G) is None  # 부착하지 않은 그래프

        heuristic = PathUtils(G)._search_heuristic(1.0)

        assert heuristic(0, 3) == pytest.approx(
            PathUtils._haversine_m(*_ALT_POS[0], *_ALT_POS[3])
        )

    def test_min_ratio가_1_미만이면_ALT를_쓰지_않는다(self):
        """ALT 거리표는 length 기준이라, length보다 작아질 수 있는 weight
        (min_ratio < 1.0)에서는 하한이 실제 비용을 넘어설 수 있다."""
        G = _alt_graph()
        attached = _attach_alt(G)

        heuristic = PathUtils(G)._search_heuristic(0.5)

        assert heuristic is not attached
        assert heuristic(0, 3) == pytest.approx(
            PathUtils._haversine_m(*_ALT_POS[0], *_ALT_POS[3]) * 0.5
        )

    def test_ALT를_써도_거리_최단경로는_그대로다(self):
        G = _alt_graph()
        expected = nx.shortest_path(G, 0, 3, weight="length")
        _attach_alt(G)

        assert PathUtils(G).astar_path(0, 3, weight="length") == expected
