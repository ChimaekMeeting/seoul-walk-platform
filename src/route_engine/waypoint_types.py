"""경유지 선택 알고리즘이 공유하는 입력과 완성 조합."""

from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite
from typing import TypedDict


class WaypointCandidate(TypedDict):
    """후보 생성 단계에서 이미 스냅한 그래프 노드와 좌표."""

    node_id: int
    lat: float
    lon: float


CostFunction = Callable[[int, int], float]


@dataclass(frozen=True)
class RouteMetrics:
    """실제 도로 경로의 총거리와 첫 통행을 제외한 재통행 거리(m)."""

    distance_m: float
    repeated_m: float

    def __post_init__(self):
        """유한한 거리와 재통행 거리의 포함 관계를 검사한다."""
        if (
            not isfinite(self.distance_m)
            or not isfinite(self.repeated_m)
            or not 0 <= self.repeated_m <= self.distance_m
        ):
            raise ValueError(
                "재통행 거리는 0 이상 총거리 이하의 유한한 값이어야 합니다."
            )

    @property
    def overlap_ratio(self) -> float:
        """재통행 거리 비율을 반환한다. 이동 거리가 0이면 0으로 정의한다."""
        return self.repeated_m / self.distance_m if self.distance_m else 0.0


RouteEvaluation = Callable[[tuple[int, ...]], RouteMetrics | None]


@dataclass(frozen=True)
class WaypointOrder:
    """출발·도착을 제외한 경유지 순서와 거리 평가 결과."""

    waypoint_ids: tuple[int, ...]
    distance_m: float
    error_m: float
    # None은 도로 경로를 평가하지 않았다는 뜻이며, 재통행 0%와 다르다.
    route_metrics: RouteMetrics | None = None
