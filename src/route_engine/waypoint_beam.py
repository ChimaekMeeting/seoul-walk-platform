"""경유지 선택·순서만 탐색하는 독립 Beam Search."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from heapq import nsmallest
from math import inf, isfinite
from typing import TypedDict


class WaypointCandidate(TypedDict):
    """경유지 후보 생성 단계에서 전달하는 그래프 노드 ID와 좌표."""

    node_id: int
    lat: float
    lon: float


CostFunction = Callable[[int, int], float]


@dataclass(frozen=True)
class WaypointOrder:
    """출발·도착을 제외한 경유지 순서와 거리 평가 결과."""

    waypoint_ids: tuple[int, ...]
    distance_m: float
    error_m: float


@dataclass(frozen=True)
class BeamResult:
    # 목표 오차순으로 정렬된 최대 beam_width개의 조합. 미발견 시 빈 튜플.
    orders: tuple[WaypointOrder, ...]
    # 도달 불가로 제외된 시도도 포함한다.
    evaluated_candidates: int
    # 캐시 적중을 포함한 cost 호출 수이며, A* 실행 횟수는 아니다.
    cost_calls: int


@dataclass(frozen=True)
class _State:
    waypoint_ids: tuple[int, ...]
    partial_m: float  # 출발지부터 마지막 경유지까지의 누적 거리
    closed_m: float  # 지금 도착지까지 연결했을 때의 총거리


def beam_search(
    *,
    candidates: Sequence[WaypointCandidate],
    cost: CostFunction,
    start_id: int,
    end_id: int,
    target_m: float,
    waypoint_count: int,
    beam_width: int,
) -> BeamResult:
    """외부 후보 풀에서 정확히 waypoint_count개의 경유지와 순서를 선택한다.

    cost는 동일한 그래프의 대칭 거리(m)를 반환하며, 도달 불가는 inf이다.
    순환 경로는 end_id=start_id로 지정한다.
    완성 조합을 찾지 못하면 orders는 비어 있다. 목표 허용 오차는 별도 판정한다.
    """
    if not isfinite(target_m) or target_m <= 0:
        raise ValueError("target_m은 유한한 양수여야 합니다.")
    for name, value in (
        ("waypoint_count", waypoint_count),
        ("beam_width", beam_width),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name}는 1 이상의 정수여야 합니다.")
    if any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in (start_id, end_id)
    ):
        raise ValueError("출발/도착 ID는 정수여야 합니다.")

    pool: list[int] = []
    seen: set[int] = set()
    for candidate in candidates:
        if not {"node_id", "lat", "lon"} <= candidate.keys():
            raise ValueError("후보에는 node_id, lat, lon이 필요합니다.")
        node_id = candidate["node_id"]
        if isinstance(node_id, bool) or not isinstance(node_id, int):
            raise ValueError("후보 node_id는 정수여야 합니다.")
        if node_id in seen:
            raise ValueError(f"중복 후보 node_id: {node_id}")
        seen.add(node_id)
        if node_id not in (start_id, end_id):
            pool.append(node_id)

    if len(pool) < waypoint_count:
        raise ValueError("출발/도착을 제외한 후보 수가 경유지 수보다 적습니다.")

    pool.sort()
    evaluated_candidates = 0
    cost_calls = 0

    def distance(a: int, b: int) -> float:
        nonlocal cost_calls
        cost_calls += 1
        value = float(cost(a, b))
        if value == inf:
            return inf
        if not isfinite(value) or value < 0:
            raise ValueError("cost는 0 이상의 거리 또는 양의 inf여야 합니다.")
        return value

    def rank(state: _State) -> tuple[float, tuple[int, ...]]:
        # 목표 거리와 비교하므로 cost의 합은 실제 이동 거리(m)여야 한다.
        # 선호 가중 비용으로 확장할 때는 선택한 구간의 실제 거리도 별도로 받아,
        # 목표 거리 오차와 선호 비용을 분리해 평가해야 한다.
        # 오차가 같으면 ID 순서로 비교해 결과를 일정하게 유지한다.
        return abs(state.closed_m - target_m), state.waypoint_ids

    def expand(states: Sequence[_State]) -> Iterator[_State]:
        nonlocal evaluated_candidates
        for state in states:
            last_id = state.waypoint_ids[-1] if state.waypoint_ids else start_id
            for next_id in pool:
                if next_id in state.waypoint_ids:
                    continue
                evaluated_candidates += 1

                leg_m = distance(last_id, next_id)
                if leg_m == inf:
                    continue
                tail_m = distance(next_id, end_id)
                if tail_m == inf:
                    continue

                partial_m = state.partial_m + leg_m
                # 도착 연결 거리는 평가에만 쓰고 다음 확장의 누적 거리에 넣지 않는다.
                closed_m = partial_m + tail_m
                if not isfinite(closed_m):
                    raise ValueError("누적 거리 계산이 유한 범위를 넘었습니다.")

                yield _State(
                    waypoint_ids=state.waypoint_ids + (next_id,),
                    partial_m=partial_m,
                    closed_m=closed_m,
                )

    # 시작 상태의 closed_m은 평가하지 않는다. 첫 확장부터 계산한다.
    beam = [_State(waypoint_ids=(), partial_m=0.0, closed_m=0.0)]

    for _ in range(waypoint_count):
        # 전체 확장 결과에서 Top-B를 고르되, 확장 상태를 한꺼번에 저장하지 않는다.
        beam = nsmallest(beam_width, expand(beam), key=rank)
        if not beam:
            break

    orders = tuple(
        WaypointOrder(
            waypoint_ids=state.waypoint_ids,
            distance_m=state.closed_m,
            error_m=abs(state.closed_m - target_m),
        )
        for state in beam
    )
    return BeamResult(
        orders=orders,
        evaluated_candidates=evaluated_candidates,
        cost_calls=cost_calls,
    )
