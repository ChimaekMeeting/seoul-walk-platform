"""경유지 경로의 재통행 측정과 Beam·ALNS 공통 비교 기준."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
from math import isclose, isfinite

from src.route_engine.waypoint_types import (
    CostFunction,
    RouteEvaluation,
    RouteMetrics,
    WaypointOrder,
)

PathFunction = Callable[[int, int], Sequence[int] | None]


class RouteEvaluator:
    """고정 무방향 그래프의 구간 경로를 공급받아 재통행을 측정한다."""

    def __init__(
        self,
        path: PathFunction,
        edge_length: CostFunction,
        *,
        cache_size: int = 1024,
    ):
        """경로·엣지 길이 공급자를 저장하고 크기가 제한된 구간 캐시를 만든다."""
        if (
            isinstance(cache_size, bool)
            or not isinstance(cache_size, int)
            or cache_size < 0
        ):
            raise ValueError("cache_size는 0 이상의 정수여야 합니다.")
        self._path = path
        self._edge_length = edge_length
        self._leg = lru_cache(maxsize=cache_size)(self._load_leg)

    def _load_leg(self, a: int, b: int):
        """한 구간을 방향 없는 도로 엣지와 길이의 튜플로 변환한다."""
        if a == b:
            return ()
        nodes = self._path(a, b)
        if nodes is None:
            return None
        nodes = tuple(nodes)
        if (
            len(nodes) < 2
            or nodes[0] != a
            or nodes[-1] != b
            or any(isinstance(n, bool) or not isinstance(n, int) for n in nodes)
        ):
            raise ValueError(
                "구간 경로는 요청한 출발·도착을 포함하는 노드 ID 열이어야 합니다."
            )
        edges = []
        for u, v in zip(nodes, nodes[1:]):
            length = float(self._edge_length(u, v))
            if not isfinite(length) or length < 0:
                raise ValueError("도로 엣지 길이는 0 이상의 유한한 거리여야 합니다.")
            edges.append(((min(u, v), max(u, v)), length))
        return tuple(edges)

    def __call__(self, stops: tuple[int, ...]) -> RouteMetrics | None:
        """출발·도착 포함 순서를 복원하고, 두 번째 통행부터 길이를 누적한다."""
        if len(stops) < 2 or any(
            isinstance(n, bool) or not isinstance(n, int) for n in stops
        ):
            raise ValueError("stops에는 출발·도착을 포함한 정수 ID가 필요합니다.")
        seen = set()
        total = repeated = 0.0
        for a, b in zip(stops, stops[1:]):
            if a == b:
                continue
            # 대칭 거리 계약에 맞춰 한 쌍에는 하나의 고정 경로를 사용한다.
            # 최단경로 동점에서 역방향 호출이 다른 길을 택하지 않도록 한다.
            edges = self._leg(min(a, b), max(a, b))
            if edges is None:
                return None
            for edge, length in edges:
                total += length
                if edge in seen:
                    repeated += length
                seen.add(edge)
        return RouteMetrics(total, repeated)

    def cache_info(self):
        """구간 캐시 적중·실제 공급자 호출 수·저장 개수를 반환한다."""
        return self._leg.cache_info()

    def cache_clear(self) -> None:
        """캐시와 통계를 지워 다음 실험을 빈 상태에서 시작한다."""
        self._leg.cache_clear()


def attach_route_metrics(
    order: WaypointOrder,
    evaluate_route: RouteEvaluation,
    start_id: int,
    end_id: int,
) -> WaypointOrder | None:
    """도로 지표를 붙이고, cost 합과 복원 경로의 실제 거리가 일치하는지 검사한다."""
    metrics = evaluate_route((start_id, *order.waypoint_ids, end_id))
    if metrics is None:
        return None
    if not isinstance(metrics, RouteMetrics):
        raise ValueError("경로 평가 공급자는 RouteMetrics 또는 None을 반환해야 합니다.")
    if not isclose(metrics.distance_m, order.distance_m, rel_tol=1e-9, abs_tol=1e-6):
        raise ValueError(
            "cost 합과 복원 경로 거리가 다릅니다. 그래프·경로 선택 기준을 확인하세요."
        )
    return replace(order, route_metrics=metrics)


@dataclass(frozen=True)
class WaypointObjective:
    """거리 전용 또는 허용 범위 안 재통행 우선 비교를 선택한다."""

    target_m: float
    tolerance_ratio: float | None = None

    def __post_init__(self):
        """목표 거리와 명시적으로 지정한 허용 오차 비율을 검사한다."""
        if (
            isinstance(self.target_m, bool)
            or not isfinite(self.target_m)
            or self.target_m <= 0
        ):
            raise ValueError("target_m은 유한한 양수여야 합니다.")
        value = self.tolerance_ratio
        if value is not None and (
            isinstance(value, bool) or not isfinite(value) or not 0 <= value < 1
        ):
            raise ValueError("tolerance_ratio는 0 이상 1 미만이어야 합니다.")

    def validate_provider(self, evaluate_route: RouteEvaluation | None) -> None:
        """재통행 모드에는 허용 오차와 경로 공급자를 반드시 함께 받는다."""
        if (self.tolerance_ratio is None) != (evaluate_route is None):
            raise ValueError("tolerance_ratio와 evaluate_route를 함께 지정해야 합니다.")
        if evaluate_route is not None and not callable(evaluate_route):
            raise ValueError(
                "evaluate_route는 호출 가능한 경로 평가 공급자여야 합니다."
            )

    def within_tolerance(self, order: WaypointOrder) -> bool:
        """오차가 목표 거리의 허용 비율 이하인지 판정한다."""
        if self.tolerance_ratio is None:
            raise ValueError("허용 오차가 지정되지 않았습니다.")
        return order.error_m <= self.target_m * self.tolerance_ratio

    def quality(self, order: WaypointOrder) -> tuple[float, float]:
        """낮을수록 좋은 주 점수와 동점 비교값을 반환한다."""
        if self.tolerance_ratio is None:
            return order.error_m, 0.0
        if order.route_metrics is None:
            raise ValueError("재통행 비교에는 실제 도로 경로 평가가 필요합니다.")
        error_ratio = order.error_m / self.target_m
        if not isfinite(error_ratio):
            raise ValueError("목표 거리 대비 오차 비율이 유한 범위를 넘었습니다.")
        overlap = order.route_metrics.overlap_ratio
        if self.within_tolerance(order):
            # 범위 안은 [0, 1], 밖은 1 초과: 범위 충족을 먼저 보장한다.
            return overlap, error_ratio
        return 1.0 + error_ratio, overlap

    def rank(self, order: WaypointOrder):
        """품질이 같으면 경유지 ID 순서로 결정해 결과를 재현한다."""
        return (*self.quality(order), order.waypoint_ids)

    def score(self, order: WaypointOrder) -> float:
        """SA 수락 확률에 사용할 주 점수를 반환한다."""
        return self.quality(order)[0]

    def is_optimal(self, order: WaypointOrder) -> bool:
        """거리와 활성화된 재통행 지표가 모두 0일 때만 조기 종료한다."""
        return order.error_m == 0 and (
            self.tolerance_ratio is None
            or (order.route_metrics is not None and order.route_metrics.repeated_m == 0)
        )
