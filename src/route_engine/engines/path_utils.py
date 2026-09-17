import math
import random
from dataclasses import dataclass
from typing import Optional, TypeVar

import networkx as nx

_PathT = TypeVar("_PathT")


@dataclass(frozen=True)
class PrunedBranch:
    """prune_dead_ends가 한 번의 반복에서 잘라낸 구간 하나의 기록(2026-09-09 계측 추가).

    "겹침 제거 로직을 겹침 기준으로 바꿀지, 아예 뺄지"를 나중에 데이터로 판단하기 위한
    순수 진단 값이다 — 이 기록을 켜도 prune_dead_ends의 반환값은 달라지지 않는다.

    현재 규칙은 중복 노드 사이 구간을 길이만 보고 지우므로, "되짚어 온 길"과 "한 바퀴
    돌아온 길"을 구분하지 못한다. overlap_ratio가 그 둘을 가른다:
        0.0  — 겹치는 엣지가 하나도 없는 순환(겹침 기준으로 바꾸면 살아남을 구간)
        0.5  — 순수 왕복(어떤 기준에서도 지워야 할 구간)
    (0.5는 waypoint_route_builder.py::edge_overlap_ratio와 같은 정의다 — 두 번째 이후
    통행분만 repeated에 더하므로 단순 왕복이 정확히 0.5가 된다.)

    interior는 이 제거로 경로에서 빠지는 노드들이다(중복 검출된 anchor 자신은 first
    위치에 그대로 남으므로 포함하지 않는다). 사라진 경유지를 어느 유형의 구간에
    귀속시킬지 판단할 때 쓴다.
    """
    anchor: int                   # 두 번 등장해 구간을 특정한 노드(살아남음)
    length_m: float               # 잘라낸 구간의 길이
    overlap_ratio: float          # 그 구간 안의 엣지 재통행 거리 비율
    interior: tuple[int, ...]     # 이 제거로 경로에서 빠지는 노드들

_R1_M: float = 30.0   # ROUT-NODE 1차 탐색 반경 (m)
_R2_M: float = 300.0  # ROUT-NODE 2차 탐색 반경 (m)

_NETWORK_FACTOR: float = 1.4          # 직선 거리 → 도로망 거리 추정 계수 (서울 도심 블록 구조 기준)
_TOLERANCE_RATIO: float = 0.1         # 허용 오차 범위 10%
_RETURN_REVISIT_PENALTY: float = 5.0  # 연결 경로가 기방문 노드를 재사용할 때의 거리 가중 배수

_EARTH_RADIUS_M: float = 6_371_000.0


def latlon_to_local_xy(lat: float, lon: float, *, lat_ref: float) -> tuple[float, float]:
    """도보 엣지 스케일(수십~수백 m) 전제의 등장방형(equirectangular) 근사 투영.
    lat_ref 위도에서의 경도 1도 실거리(cos(lat_ref) 보정)를 반영해, 위경도를 그대로
    평면 좌표로 쓸 때 생기는 동서 방향 왜곡을 없앤다. 구간이 수 km 이상으로 길어지거나
    넓은 지역을 가로지르면 이 근사의 오차도 커지므로 그때는 재검토가 필요하다."""
    lat_rad, lon_rad, ref_rad = math.radians(lat), math.radians(lon), math.radians(lat_ref)
    return (lon_rad * math.cos(ref_rad) * _EARTH_RADIUS_M, lat_rad * _EARTH_RADIUS_M)


def turn_angle(
    prev_xy: tuple[float, float],
    curr_xy: tuple[float, float],
    next_xy: tuple[float, float],
) -> float | None:
    """평면(또는 동일 기준으로 투영된) 좌표 3개에서 curr 지점의 회전각(도, 0~180)을
    반환한다. 0=직진, 90=직각 회전, 180=완전한 유턴(좌우 방향은 구분하지 않음).
    원시 위경도(도)는 직접 넣지 않는다 — latlon_to_local_xy로 투영한 뒤 넣을 것.
    직전==현재 또는 현재==다음(길이 0 벡터)이면 회전을 정의할 수 없어 None을 반환한다."""
    v1x, v1y = curr_xy[0] - prev_xy[0], curr_xy[1] - prev_xy[1]
    v2x, v2y = next_xy[0] - curr_xy[0], next_xy[1] - curr_xy[1]
    n1, n2 = math.hypot(v1x, v1y), math.hypot(v2x, v2y)
    if n1 == 0.0 or n2 == 0.0:
        return None
    cosine = max(-1.0, min(1.0, (v1x * v2x + v1y * v2y) / (n1 * n2)))  # acos 정의역([-1,1]) clamp
    return math.degrees(math.acos(cosine))


def _undefined_turn_reason(G: nx.Graph, prev_node, curr_node, next_node) -> str:
    """turn_angle_at이 None을 반환했을 때만 호출되는 원인 분류(예외 경로라 비용 무시 가능)."""
    for nd_id in (prev_node, curr_node, next_node):
        nd = G.nodes[nd_id]
        if "lat" not in nd or "lon" not in nd:
            return "missing_coordinate"
    return "zero_length_segment"


def turn_angle_at(G: nx.Graph, prev_node, curr_node, next_node) -> float | None:
    """그래프 노드 3개(직전·현재·다음)에서 curr 지점의 회전각(도). turn_angle의 그래프
    래퍼 — 노드 lat/lon을 curr 위도 기준 로컬 평면으로 투영한 뒤 turn_angle에 넘긴다.
    좌표 누락 또는 길이 0 벡터면 None. 특정 탐색 엔진에 종속되지 않는 공용 함수이지만
    그래프 좌표 상태에는 의존한다(엄밀한 순수 함수는 turn_angle/latlon_to_local_xy 쪽).
    calc_distance(엣지 속성 length 합산)와는 좌표 소스가 무관한 별개 계산이다."""
    pn, cn, nn = G.nodes[prev_node], G.nodes[curr_node], G.nodes[next_node]
    if any(k not in nd for nd in (pn, cn, nn) for k in ("lat", "lon")):
        return None
    lat_ref = cn["lat"]
    p_xy = latlon_to_local_xy(pn["lat"], pn["lon"], lat_ref=lat_ref)
    c_xy = latlon_to_local_xy(cn["lat"], cn["lon"], lat_ref=lat_ref)
    n_xy = latlon_to_local_xy(nn["lat"], nn["lon"], lat_ref=lat_ref)
    return turn_angle(p_xy, c_xy, n_xy)


def count_turns_at_or_above(angles_deg, threshold_deg: float) -> int:
    """회전각 목록에서 threshold_deg 이상인 것의 개수. 45/60/90도 등은 아직 검증된
    인간공학적 기준이 아니라 잠정 운영 임계값이므로, TurnMetrics에 특정 값을 필드로
    고정하지 않고 분석 단계에서 원하는 후보값마다 이 함수로 동적 계산한다."""
    return sum(1 for a in angles_deg if a >= threshold_deg)


@dataclass(frozen=True)
class TurnAngleResult:
    """turn_angle_result()의 상세 반환값. angles_deg는 정의 가능했던 회전각만 담고,
    undefined_reasons는 정의 불가 지점의 원인별 개수를 담는다(0으로 숨기지 않음)."""
    angles_deg: list[float]
    undefined_reasons: dict[str, int]


@dataclass(frozen=True)
class TurnMetrics:
    """경로의 회전 관련 통계(진단·비교용, 엔진 accept/reject 기준에는 미사용).
    급회전 개수(45/60/90도 등)는 여기 필드로 두지 않는다 — count_turns_at_or_above를
    후보 임계값마다 별도 호출해서 구한다(임계값 근거가 아직 확정되지 않았기 때문)."""
    total_turn_deg: float
    max_turn_deg: float
    candidate_turn_count: int
    defined_turn_count: int
    undefined_turn_count: int
    undefined_turn_reasons: dict[str, int]
    turn_deg_per_km: float | None


class PathUtils:
    def __init__(self, G: nx.Graph):
        self.G = G

    @staticmethod
    def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """
        두 좌표 사이의 Haversine 거리(미터)를 반환합니다.
        """
        R  = 6_371_000.0
        p1 = math.radians(lat1)
        p2 = math.radians(lat2)
        dp = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a  = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def find_nearest_node(
        self,
        lat: float,
        lon: float,
        max_dist_m: float | None = None,
    ) -> int | None:
        """
        위경도에서 그래프상 가장 가까운 노드 ID를 반환합니다.
        max_dist_m 지정 시 해당 반경(m) 이내 노드만 탐색합니다.

        후보를 최대 연결요소로 제한해, 서로 다른 호출(예: 출발점과 도착점)이 고른
        노드끼리 항상 도달 가능함을 보장합니다(docs/route_engine/README.md의
        `_largest_component_nodes` 설명 참고). 엣지가 하나도 없는 그래프(모든 노드가
        독립된 성분)에서는 이 제한이 의미가 없으므로(성분 크기가 전부 동일해 어느
        쪽을 골라도 더 "안전"하지 않음) 전체 노드를 후보로 씁니다. 빈 그래프는 None을
        반환합니다.
        """
        if self.G.number_of_nodes() == 0:
            return None
        if self.G.number_of_edges() == 0:
            largest_cc = set(self.G.nodes)
        elif self.G.is_directed():
            largest_cc = max(nx.weakly_connected_components(self.G), key=len)
        else:
            largest_cc = max(nx.connected_components(self.G), key=len)
        min_dist = float("inf")
        nearest  = None
        for node_id, data in self.G.nodes(data=True):
            if node_id not in largest_cc:
                continue
            node_lat = data.get("lat")
            node_lon = data.get("lon")
            if node_lat is None or node_lon is None:
                continue
            dist_m = self._haversine_m(lat, lon, node_lat, node_lon)
            if max_dist_m is not None and dist_m > max_dist_m:
                continue
            if dist_m < min_dist:
                min_dist = dist_m
                nearest  = node_id
        return nearest

    def find_nearest_node_with_expansion(
        self,
        lat: float,
        lon: float,
        r1_m: float = _R1_M,
        r2_m: float = _R2_M,
    ) -> int | None:
        """
        ROUT-NODE-001/002: R1 → R2 2단계 반경 확장 탐색.
        R1 이내에 없으면 R2까지 확장하여 재탐색합니다.
        두 단계 모두 실패하면 None을 반환합니다.
        """
        node = self.find_nearest_node(lat, lon, max_dist_m=r1_m)
        if node is None:
            node = self.find_nearest_node(lat, lon, max_dist_m=r2_m)
        return node

    def extract_coordinates(self, node_list: list) -> list:
        """
        노드 ID 리스트 → [[lat, lon], ...] 변환
        """
        result = []
        for n in node_list:
            if n not in self.G.nodes:
                continue
            nd  = self.G.nodes[n]
            lat = nd.get("lat")
            lon = nd.get("lon")
            # 직접 접근(["lat"])은 속성 없는 노드에서 KeyError 발생 → .get()으로 안전 처리
            if lat is not None and lon is not None:
                result.append([lat, lon])
        return result

    def _describe_pruned_branch(self, pruned: list, first: int, last: int) -> PrunedBranch:
        """잘라내기 직전의 구간 하나를 PrunedBranch로 기록합니다(진단 전용).

        구간 안에서 같은 도로 엣지가 두 번째 이후로 통행되는 분량만 repeated에 더해
        재통행 비율을 구합니다 — waypoint_route_builder.py::edge_overlap_ratio와 같은
        정의이며, 순환 import를 피하려고 여기서 다시 계산합니다.
        """
        seen: set[frozenset] = set()
        total = repeated = 0.0
        for j in range(first, last):
            length = (self.G.get_edge_data(pruned[j], pruned[j + 1]) or {}).get("length", 0)
            key = frozenset((pruned[j], pruned[j + 1]))
            total += length
            if key in seen:
                repeated += length
            seen.add(key)
        return PrunedBranch(
            anchor=pruned[first],
            length_m=total,
            overlap_ratio=(repeated / total if total else 0.0),
            interior=tuple(pruned[first + 1:last]),
        )

    def prune_dead_ends(
        self, path_nodes: list, max_branch_length: float = 400.0,
        sink: Optional[list] = None,
    ) -> list:
        """
        왕복 가지치기를 수행합니다.
        같은 노드가 두 번 등장하는 구간 중 max_branch_length 미만인 것을 반복 제거합니다.

        max_branch_length는 "총 왕복 길이"의 상한이 아니라 **한 번의 제거에 적용되는**
        상한입니다(2026-09-09 확인). 제거 후 루프가 다시 돌면서 더 짧아진 왕복이 새로
        드러나므로, 안쪽 한 쌍만 임계값 아래면 순수 왕복은 총 길이와 무관하게 끝까지
        붕괴합니다(합성 격자, 엣지 약 159m: 왕복 1~4구간 318~1270m가 모두 노드 1개로 축소).

        sink에 리스트를 넘기면 제거한 구간마다 PrunedBranch를 append합니다(진단 전용,
        기본값 None이면 아무 비용도 들지 않고 반환값도 완전히 동일합니다). 현재 규칙은
        "짧은 닫힌 부분경로"를 지우므로 겹치는 엣지가 하나도 없는 블록 순환까지 지워지는데,
        그 비율을 실측으로 확인해 겹침 기준 전환·제거 여부를 판단하기 위한 훅입니다.
        """
        pruned  = list(path_nodes)
        changed = True
        while changed:
            changed        = False
            node_positions = {}   # 노드별 첫 등장 인덱스
            candidates     = []   # 제거 후보 (branch_length, 시작, 끝)
            for i, node in enumerate(pruned):
                if node in node_positions:
                    first = node_positions[node]  # 이전 등장 위치
                    branch_length = sum(
                        (self.G.get_edge_data(pruned[j], pruned[j + 1]) or {}).get("length", 0)
                        for j in range(first, i)
                    )  # 왕복 구간 길이
                    if branch_length < max_branch_length:
                        candidates.append((branch_length, first, i))
                else:
                    node_positions[node] = i
            if candidates:
                _, first, last = min(candidates, key=lambda x: x[0])  # 가장 짧은 가지 선택
                if sink is not None:
                    sink.append(self._describe_pruned_branch(pruned, first, last))
                pruned  = pruned[:first + 1] + pruned[last + 1:]       # 해당 구간 제거
                changed = True
        return pruned

    def remove_dead_ends(self) -> nx.Graph:
        """
        degree=1인 막힌 끝 노드를 반복 제거한 새 그래프를 반환합니다.
        """
        G = self.G.copy()
        while True:
            dead_ends = [n for n, d in G.degree() if d == 1]  # 연결 엣지가 1개뿐인 노드
            if not dead_ends:
                break
            G.remove_nodes_from(dead_ends)
        return G

    def _edge_distance_m(self, u: int, v: int) -> float:
        """calc_distance와 동일한 규칙으로 u-v 엣지의 길이를 반환한다(무방향 단순
        그래프라 u,v 순서 무관). 엣지가 없거나 length 속성이 없으면 조용히 0으로
        처리한다(기존 호출부와의 동작 일관성 우선 — 실제 엔진이 만드는 경로는 항상
        유효한 연속 엣지로 구성되므로 이 경우가 발생하지 않는다는 전제)."""
        return (self.G.get_edge_data(u, v) or {}).get("length", 0)

    def calc_distance(self, nodes: list[int]) -> float:
        """
        노드 목록의 총 이동 거리(미터)를 반환합니다.
        """
        return sum(
            self._edge_distance_m(nodes[i], nodes[i + 1])
            for i in range(len(nodes) - 1)
        )  # 인접 노드 쌍의 length 합산

    @staticmethod
    def _normalized_nodes(path: list[int], *, closed: bool) -> list[int]:
        """closed=True일 때, 시작 노드가 끝에 중복된 표현([n0,..,nk,n0])과 중복 없는
        표현([n0,..,nk])을 동일하게 처리하기 위해 마지막 중복을 제거한다."""
        nodes = list(path)
        if closed and len(nodes) > 1 and nodes[0] == nodes[-1]:
            nodes.pop()
        return nodes

    def path_distance_m(self, path: list[int], *, closed: bool = False) -> float:
        """경로의 총 이동 거리(m). closed=True면 입력이 시작 노드 중복 여부와 무관하게
        마지막→시작 이음매 구간 거리를 정확히 1회만 더한다(중복 계산도 누락도 없음).
        거리는 노드 좌표가 아니라 엣지 length 속성(DB 사전계산값)을 합산한다 —
        회전각(노드 좌표 기반)과는 데이터 소스가 무관한 별개 계산이다."""
        nodes = self._normalized_nodes(path, closed=closed)
        if len(nodes) < 2:
            return 0.0
        distance_m = self.calc_distance(nodes)
        if closed:
            distance_m += self._edge_distance_m(nodes[-1], nodes[0])
        return distance_m

    def turn_angle_result(self, path: list[int], *, closed: bool = False) -> TurnAngleResult:
        """회전각 목록과 정의 불가능한 원인별 집계를 반환한다.

        closed=True면 시작 노드 중복 여부(있든 없든)와 무관하게 경로를 닫힌 루프로
        보고, 서로 다른 노드가 3개 미만이면 계산하지 않는다. 닫힌 루프는 "메인 구간 +
        이음매 패치" 방식이 아니라 전체 노드를 모듈러 인덱스로 순회해, n개 노드에
        대해 정확히 n개의 회전을 빠짐없이 계산한다(패치 방식은 마지막 노드의 회전이
        누락되는 버그가 있었음 — 삼각형 순환으로 검증: 메인+패치는 2개, 모듈러 순회는
        3개가 나와야 정답).

        내부 노드 재방문(닫힌 경로 여부와 무관하게, 예: [n0,n1,n2,n1])이 있어도 노드
        ID가 아니라 리스트 위치 기준으로 그대로 회전량을 계산한다 — 회전량은 실제
        이동 순서의 방향 변화를 재는 지표이고, 자기중첩 여부는 edge_overlap_ratio 등
        별도 지표가 맡는다."""
        nodes = self._normalized_nodes(path, closed=closed)
        n = len(nodes)
        if closed:
            if len(set(nodes)) < 3:
                return TurnAngleResult([], {})
            index_range = range(n)
        else:
            if n < 3:
                return TurnAngleResult([], {})
            index_range = range(1, n - 1)

        angles: list[float] = []
        undefined_reasons: dict[str, int] = {}
        for i in index_range:
            prev_node, curr_node, next_node = nodes[(i - 1) % n], nodes[i], nodes[(i + 1) % n]
            angle = turn_angle_at(self.G, prev_node, curr_node, next_node)
            if angle is None:
                reason = _undefined_turn_reason(self.G, prev_node, curr_node, next_node)
                undefined_reasons[reason] = undefined_reasons.get(reason, 0) + 1
            else:
                angles.append(angle)
        return TurnAngleResult(angles, undefined_reasons)

    def turn_angles(self, path: list[int], *, closed: bool = False) -> list[float]:
        """경로에서 정의 가능한 회전각만 도 단위 목록으로 반환한다(편의 함수)."""
        return self.turn_angle_result(path, closed=closed).angles_deg

    def turn_metrics(self, path: list[int], *, closed: bool = False) -> TurnMetrics:
        """경로의 회전 관련 통계(진단·비교용, 엔진 accept/reject 기준에는 미사용)."""
        result = self.turn_angle_result(path, closed=closed)
        angles, undefined_reasons = result.angles_deg, result.undefined_reasons
        undefined_count = sum(undefined_reasons.values())
        distance_km = self.path_distance_m(path, closed=closed) / 1000.0
        return TurnMetrics(
            total_turn_deg=sum(angles),
            max_turn_deg=max(angles, default=0.0),
            candidate_turn_count=len(angles) + undefined_count,
            defined_turn_count=len(angles),
            undefined_turn_count=undefined_count,
            undefined_turn_reasons=undefined_reasons,
            turn_deg_per_km=(sum(angles) / distance_km) if distance_km > 1e-6 else None,
        )

    # ── 경로 엔진 공통 평가 도구 (beam / grasp 공유) ─────────────────────────────
    def est_network_dist(self, node: int, target: int) -> float:
        """
        node에서 target 노드까지의 추정 도로망 거리(직선 × 도로망 계수)를 반환합니다.
        순환의 복귀거리·편도의 남은거리 추정에 공통으로 사용합니다.
        """
        t = self.G.nodes[target]
        t_lat, t_lon = t.get("lat", 0), t.get("lon", 0)
        d = self.G.nodes[node]
        straight = self._haversine_m(d.get("lat", t_lat), d.get("lon", t_lon), t_lat, t_lon)
        return straight * _NETWORK_FACTOR

    def objective(self, value: float, dist: float, cost: float, target_m: float) -> tuple:
        """
        정렬용 키 튜플 (거리 합격 우선 → 그 안에서 품질)을 반환합니다.
        """
        over    = max(0.0, abs(value - target_m) - _TOLERANCE_RATIO * target_m)  # |실제 오차| - 허용 오차
        density = cost / max(dist, 1.0)  # 누적 비용 / 거리
        return (over, density)

    def metrics(self, path: list[int]) -> tuple:
        """
        경로의 (총 이동 거리 m, 누적 custom_score)를 반환합니다.
        """
        total_m = sum(
            (self.G.get_edge_data(path[i], path[i + 1]) or {}).get("length", 0)
            for i in range(len(path) - 1)
        )
        full_cost = sum(
            (self.G.get_edge_data(path[i], path[i + 1]) or {}).get("custom_score", 1.0)
            for i in range(len(path) - 1)
        )
        return total_m, full_cost  # 누적 거리, 누적 비용

    def route_key(self, path: list[int], target_m: float) -> tuple:
        """
        완성 경로의 평가 키와 노드열을 반환합니다.
        """
        total_m, full_cost = self.metrics(path)
        return self.objective(total_m, total_m, full_cost, target_m) + (tuple(path),)

    # ── 후보 다양화(safety/nature/slope/convenience/accessibility 벡터) ──────────
    @staticmethod
    def path_score_vector(path: list[int], vector_lookup: dict) -> dict[str, float]:
        """
        scoring_engine.compute_score_vector()가 만든 edge별 벡터를 경로를 따라 성분별로 합산합니다.
        vector_lookup에 없는 edge(이론상 없어야 하지만 방어적으로)는 0으로 취급합니다.

        path: 노드 id lst: [1, 2, 3, ...]
        vector_loockup: {(u,v): {"safety": cost, ...}, ...}
        """
        totals: dict[str, float] = {}
        for i in range(len(path) - 1):
            edge_vector = vector_lookup.get((path[i], path[i + 1])) or {}  # edge 순회
            for dim, cost in edge_vector.items():
                totals[dim] = totals.get(dim, 0.0) + cost
        return totals

    @staticmethod
    def vector_distance(a: dict[str, float], b: dict[str, float]) -> float:
        """
        두 score vector 사이의 유클리드 거리. 각 차원이 이미 같은 단위(미터)라
        추가 정규화 없이 그대로 비교합니다.
        """
        keys = set(a) | set(b)
        return math.sqrt(sum((a.get(k, 0.0) - b.get(k, 0.0)) ** 2 for k in keys))

    @staticmethod
    def select_diverse_paths(
        candidates: list[tuple[dict, _PathT]],
        k: int = 3,
    ) -> list[_PathT]:
        """
        candidates[0](이미 정해진 대표 후보, 기존 스칼라 키 기준 1등)을 기준으로,
        나머지 후보 중 벡터 공간에서 서로·이미 뽑힌 후보로부터 최대한 먼 (k-1)개를
        greedy farthest-point(k-center) 방식으로 추가 선택합니다.
        candidates가 k개 미만이면 있는 만큼만 반환합니다.

        인자: candidates = [(score_vector, payload), ...] — payload는 노드 ID 리스트뿐
        아니라 WalkRouteResponse 등 무엇이든 될 수 있다(그대로 통과시키기만 함).
        반환: 선택된 payload 목록(최대 k개, candidates[0]의 payload가 항상 첫 번째)
        """
        if not candidates:
            return []

        selected = [candidates[0]]
        remaining = list(candidates[1:])

        while remaining and len(selected) < k:  # 아직 경로 후보 k를 다 못 채웠다면
            best_idx, best_min_dist = None, -1.0
            for idx, (vec, _) in enumerate(remaining):
                min_dist = min(PathUtils.vector_distance(vec, s_vec) for s_vec, _ in selected)  # 벡터 간 유사도 측정
                if min_dist > best_min_dist:
                    best_min_dist, best_idx = min_dist, idx  # 선택된 후보와 비교했을 때, 가장 거리가 먼 경로를 후보로 등록
            selected.append(remaining.pop(best_idx))

        return [path for _, path in selected]

    @staticmethod
    def min_cost_length_ratio(G: nx.Graph, cost_attr: str = "custom_score") -> float:
        """
        그래프 전체에서 (cost_attr / length)의 최솟값을 반환합니다.
        Haversine 직선거리(m) × 이 값을 A* admissible heuristic으로 쓰면, cost_attr이
        length보다 작아질 수 있는(custom_score처럼 안전·자연 등으로 할인되는) weight를
        쓰더라도 휴리스틱이 실제 비용을 과대추정하지 않습니다.
        """
        return min(
            (data.get(cost_attr, 1.0) or 1.0) / max(data.get("length", 1.0) or 1.0, 1e-6)
            for _, _, data in G.edges(data=True)
        )

    def astar_path(self, source: int, target: int, weight, min_ratio: float = 1.0) -> list[int]:
        """
        nx.astar_path 래퍼 — Haversine 직선거리(min_ratio로 스케일)를 admissible heuristic으로
        씁니다. weight가 length 그대로면 기본값(1.0)으로 충분합니다. custom_score처럼 length보다
        작아질 수 있는 weight를 쓸 때는 min_cost_length_ratio(...)로 구한 값을 넘겨야
        admissible이 유지됩니다(안 넘기면 A*가 최적이 아닌 경로를 반환할 수 있음).
        경로가 없으면 nx.shortest_path와 동일하게 nx.NetworkXNoPath를 던집니다.
        """
        def _h(u, v, _min_ratio=min_ratio):
            nu, nv = self.G.nodes[u], self.G.nodes[v]
            return self._haversine_m(
                nu.get("lat", 0), nu.get("lon", 0), nv.get("lat", 0), nv.get("lon", 0)
            ) * _min_ratio
        return nx.astar_path(self.G, source, target, heuristic=_h, weight=weight)

    def connect_to(
        self,
        nodes: list[int],
        visited: set,
        target: int,
        revisit_penalty: float = _RETURN_REVISIT_PENALTY,
    ):
        """
        경로 끝(nodes[-1]) → target 최단 연결(기방문 노드 재사용 시 패널티 → 중복 억제).
        순환의 복귀 연결(target=출발지)·편도의 도착 연결(target=도착지)에 공통 사용합니다.
        반환: 완성된 경로, 연결 불가 시 None.
        """
        if nodes[-1] == target:
            return nodes

        def _weight(u, v, d, _visited=visited):
            penalty = revisit_penalty if (v in _visited and v != target) else 1.0
            return d.get("length", 1.0) * penalty

        try:
            # _weight의 기본값이 length(m) 그대로이고 revisit_penalty(≥1)는 비용을 늘리기만
            # 하므로, Haversine 직선거리를 그대로 써도(min_ratio=1.0 기본값) admissible하다.
            tail = self.astar_path(nodes[-1], target, weight=_weight)
        except nx.NetworkXNoPath:
            return None
        return nodes + tail[1:]  # 바깥 경로 + 연결 경로(중복 노드 제거)
