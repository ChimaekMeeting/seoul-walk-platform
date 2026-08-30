"""경유지 선택 알고리즘이 공유하는 입력과 완성 조합."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypedDict


class WaypointCandidate(TypedDict):
    """후보 생성 단계에서 이미 스냅한 그래프 노드와 좌표."""

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
