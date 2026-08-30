"""외부 초기 경유지 조합의 선택·순서를 개선하는 독립 ALNS."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import ceil, exp, inf, isfinite
from random import Random

from src.route_engine.waypoint_evaluation import WaypointObjective, attach_route_metrics
from src.route_engine.waypoint_types import (
    CostFunction,
    RouteEvaluation,
    WaypointCandidate,
    WaypointOrder,
)


@dataclass(frozen=True)
class ALNSConfig:
    """기본값은 실험 시작값이며, 서비스 성능을 보장하는 튜닝값이 아니다."""

    iterations: int = 200  # 최대 제거·복구 시도 수
    removal_fraction: float = 0.3  # 한 번에 제거할 비율. 개수는 ceil(N * 비율).
    start_temperature_m: float = 100.0  # 악화된 거리 오차를 수락하는 초기 척도(m)
    cooling_rate: float = 0.99  # 완료 시도마다 온도에 곱하는 비율
    segment_length: int = 20  # 연산자 성과를 모아 가중치를 갱신하는 주기
    reaction_factor: float = 0.2  # 새 평균 성과 반영률. 0이면 기존 가중치 유지.
    candidate_limit: int | None = None  # None이면 복구 후보 풀을 줄이지 않는다.
    max_cost_calls: int | None = None  # None이면 callback 호출 횟수를 제한하지 않는다.
    seed: int = 0  # 같은 입력·설정에서 난수 선택을 재현하기 위한 값
    start_temperature_score: float | None = (
        None  # 재통행 모드의 무차원 온도. 명시 입력.
    )


@dataclass(frozen=True)
class OperatorStats:
    name: str
    uses: int
    weight: float


@dataclass(frozen=True)
class ALNSResult:
    best: WaypointOrder
    current: WaypointOrder
    iterations: int  # 착수한 제거·복구 횟수. 예산으로 중단된 시도도 포함한다.
    accepted_moves: int
    failed_repairs: int
    evaluated_orders: int
    cost_calls: int  # 캐시 적중을 포함하며 실제 A* 실행 횟수와 다르다.
    stop_reason: str
    destroy_stats: tuple[OperatorStats, ...]
    repair_stats: tuple[OperatorStats, ...]
    route_evaluations: int = 0


class _CostBudgetExhausted(Exception):
    pass


class _Evaluator:
    def __init__(
        self,
        cost,
        start_id,
        end_id,
        target_m,
        max_cost_calls,
        evaluate_route=None,
        tolerance_ratio=None,
    ):
        """거리 공급자와 평가 조건을 저장하고 측정 카운터를 초기화한다."""
        self.cost = cost
        self.start_id, self.end_id = start_id, end_id
        self.target_m = target_m
        self.max_cost_calls = max_cost_calls
        self.cost_calls = 0
        self.evaluated_orders = 0
        self.objective = WaypointObjective(target_m, tolerance_ratio)
        self.objective.validate_provider(evaluate_route)
        self.evaluate_route = evaluate_route
        self.route_evaluations = 0

    def evaluate(self, ids: tuple[int, ...]) -> WaypointOrder | None:
        """출발·도착 포함 거리와 선택적 재통행을 평가한다. 도달 불가는 None이다."""
        self.evaluated_orders += 1
        stops = (self.start_id, *ids, self.end_id)
        total = 0.0
        for a, b in zip(stops, stops[1:]):
            if (
                self.max_cost_calls is not None
                and self.cost_calls >= self.max_cost_calls
            ):
                raise _CostBudgetExhausted
            self.cost_calls += 1
            distance = float(self.cost(a, b))
            if distance == inf:
                return None
            if not isfinite(distance) or distance < 0:
                raise ValueError("cost는 0 이상의 거리 또는 양의 inf여야 합니다.")
            total += distance
            if not isfinite(total):
                raise ValueError("누적 거리 계산이 유한 범위를 넘었습니다.")
        # 목표 거리와 비교하므로 cost의 합은 실제 이동 거리(m)여야 한다.
        # 선호 가중 비용으로 확장할 때는 선택한 구간의 실제 거리도 별도로 받아,
        # 목표 거리 오차와 선호 비용을 분리해 평가해야 한다.
        order = WaypointOrder(ids, total, abs(total - self.target_m))
        if self.evaluate_route is not None:
            self.route_evaluations += 1
            return attach_route_metrics(
                order, self.evaluate_route, self.start_id, self.end_id
            )
        return order


class _AdaptivePool:
    def __init__(self, names: tuple[str, ...]):
        """연산자를 동일 가중치로 시작하고 전체·세그먼트별 성과를 준비한다."""
        self.names = names
        self.weights = [1.0] * len(names)
        self.uses = [0] * len(names)
        self.segment_uses = [0] * len(names)
        self.scores = [0.0] * len(names)

    def choose(self, rng: Random) -> int:
        """가중치에 비례해 연산자를 하나 뽑고 사용 횟수를 기록한다."""
        index = rng.choices(range(len(self.names)), weights=self.weights, k=1)[0]
        self.uses[index] += 1
        self.segment_uses[index] += 1
        return index

    def update(self, reaction: float) -> None:
        """기존 가중치와 세그먼트 평균 보상을 혼합한 뒤 구간 통계를 초기화한다."""
        for i, uses in enumerate(self.segment_uses):
            if uses:
                average = self.scores[i] / uses
                # 성과가 없는 연산자도 이후 다시 선택될 가능성을 남긴다.
                self.weights[i] = max(
                    1e-6, (1 - reaction) * self.weights[i] + reaction * average
                )
        self.segment_uses = [0] * len(self.names)
        self.scores = [0.0] * len(self.names)

    def snapshot(self) -> tuple[OperatorStats, ...]:
        """실행 결과에 포함할 연산자별 사용 횟수와 가중치를 반환한다."""
        return tuple(
            OperatorStats(name, uses, weight)
            for name, uses, weight in zip(self.names, self.uses, self.weights)
        )


def _destroy(ids, count, method, rng, circular):
    """무작위 위치 또는 연속 구간을 제거하고 남은 경유지의 순서는 보존한다."""
    if method == "random":
        removed = set(rng.sample(range(len(ids)), count))
    else:
        # 순환에서는 출발지를 사이에 둔 끝·처음 경유지도 연속 구간으로 본다.
        start = rng.randrange(len(ids) if circular else len(ids) - count + 1)
        removed = {(start + offset) % len(ids) for offset in range(count)}
    return tuple(node for i, node in enumerate(ids) if i not in removed)


def _repair(partial, pool, count, method, evaluator, rng, candidate_limit):
    """미선택 후보를 삽입해 count개로 복구한다. 채우지 못하면 None을 반환한다.

    greedy는 후보·위치 전체에서 평가가 가장 좋은 삽입을 고른다. random_order는
    섞인 순서에서 첫 삽입 가능 후보를 골라 그 후보의 가장 좋은 위치에 넣는다.
    """
    selected = set(partial)
    available = [node for node in pool if node not in selected]
    # 비싼 cost 호출 전에 후보를 제한한다. None이면 전체 후보를 평가한다.
    if candidate_limit is not None and len(available) > candidate_limit:
        available = sorted(rng.sample(available, candidate_limit))
    if method == "random_order":
        rng.shuffle(available)
    order = None
    while len(partial) < count:
        chosen = None
        for node in available:
            best_position = None
            for position in range(len(partial) + 1):
                ids = partial[:position] + (node,) + partial[position:]
                candidate = evaluator.evaluate(ids)
                if candidate is not None and (
                    best_position is None
                    or evaluator.objective.rank(candidate)
                    < evaluator.objective.rank(best_position)
                ):
                    best_position = candidate
            if best_position is not None:
                if chosen is None or evaluator.objective.rank(
                    best_position
                ) < evaluator.objective.rank(chosen):
                    chosen = best_position
                if method == "random_order":
                    break
        if chosen is None:
            return None
        added = next(node for node in chosen.waypoint_ids if node not in selected)
        available.remove(added)
        selected.add(added)
        partial, order = chosen.waypoint_ids, chosen
    return order


def _accept(delta: float, temperature: float, rng: Random) -> bool:
    """주 평가값 증가량 delta가 양수이면 exp(-delta / T) 확률로 수락한다.

    거리 전용은 m, 재통행 모드는 무차원 점수와 같은 단위의 온도를 사용한다.
    주 점수 개선·동점은 수락하고, T=0이면 주 점수가 나빠진 해는 거절한다.
    악화 폭이 작거나 온도가 높을수록 수락 확률이 높다.
    """
    if delta <= 0:
        return True
    if temperature <= 0:
        return False
    probability = exp(-delta / temperature)
    return rng.random() < probability


def _integer(name, value, minimum=0):
    """bool을 제외한 정수인지와 최솟값을 검사한다."""
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name}은 {minimum} 이상의 정수여야 합니다.")


def _validate(candidates, initial_ids, start_id, end_id, target_m, config):
    """입력·설정의 유효성을 검사하고 정렬한 후보 ID와 제거 개수를 반환한다."""
    for name, value in (("start_id", start_id), ("end_id", end_id)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name}는 정수여야 합니다.")
    if isinstance(target_m, bool) or not isfinite(target_m) or target_m <= 0:
        raise ValueError("target_m은 유한한 양수여야 합니다.")
    _integer("iterations", config.iterations)
    _integer("segment_length", config.segment_length, 1)
    if isinstance(config.seed, bool) or not isinstance(config.seed, int):
        raise ValueError("seed는 정수여야 합니다.")
    for name, value, allow_zero in (
        ("removal_fraction", config.removal_fraction, False),
        ("cooling_rate", config.cooling_rate, False),
        ("reaction_factor", config.reaction_factor, True),
    ):
        if (
            isinstance(value, bool)
            or not isfinite(value)
            or value > 1
            or value < 0
            or (value == 0 and not allow_zero)
        ):
            raise ValueError(f"{name}의 범위가 올바르지 않습니다.")
    if (
        isinstance(config.start_temperature_m, bool)
        or not isfinite(config.start_temperature_m)
        or config.start_temperature_m < 0
    ):
        raise ValueError("start_temperature_m은 유한한 0 이상의 값이어야 합니다.")
    if config.start_temperature_score is not None and (
        isinstance(config.start_temperature_score, bool)
        or not isfinite(config.start_temperature_score)
        or config.start_temperature_score < 0
    ):
        raise ValueError("start_temperature_score는 유한한 0 이상의 값이어야 합니다.")
    pool = set()
    for candidate in candidates:
        if not {"node_id", "lat", "lon"} <= candidate.keys():
            raise ValueError("후보에는 node_id, lat, lon이 필요합니다.")
        node = candidate["node_id"]
        if isinstance(node, bool) or not isinstance(node, int) or node in pool:
            raise ValueError("후보 ID는 중복 없는 정수여야 합니다.")
        pool.add(node)
    pool.difference_update((start_id, end_id))
    if (
        not initial_ids
        or any(
            isinstance(node, bool) or not isinstance(node, int) or node not in pool
            for node in initial_ids
        )
        or len(set(initial_ids)) != len(initial_ids)
    ):
        raise ValueError("초기 순서는 후보 풀의 중복 없는 경유지 ID로 구성해야 합니다.")
    remove_count = max(1, ceil(len(initial_ids) * config.removal_fraction))
    if config.candidate_limit is not None:
        _integer("candidate_limit", config.candidate_limit, remove_count)
    if config.max_cost_calls is not None:
        _integer("max_cost_calls", config.max_cost_calls, len(initial_ids) + 1)
    return tuple(sorted(pool)), remove_count


def alns_search(
    *,
    candidates: Sequence[WaypointCandidate],
    cost: CostFunction,
    initial_ids: Sequence[int],
    start_id: int,
    end_id: int,
    target_m: float,
    config: ALNSConfig = ALNSConfig(),
    tolerance_ratio: float | None = None,
    evaluate_route: RouteEvaluation | None = None,
) -> ALNSResult:
    """초기 경유지 개수를 유지하며 선택·순서를 개선하고 역대 최적 조합을 반환한다.

    initial_ids에는 출발·도착을 넣지 않는다. cost는 고정 그래프의 대칭 거리(m)다.
    초기 해의 도달 불가는 ValueError, 탐색 중 복구 실패는 해당 시도만 폐기한다.
    재통행 평가 시 허용 오차·경로 공급자·start_temperature_score를 함께 지정한다.
    공급자 예외는 전달하며, 후보 생성·도로 경로 탐색은 외부에 위임한다.
    """
    initial_ids = tuple(initial_ids)
    pool, remove_count = _validate(
        candidates, initial_ids, start_id, end_id, target_m, config
    )
    evaluator = _Evaluator(
        cost,
        start_id,
        end_id,
        target_m,
        config.max_cost_calls,
        evaluate_route,
        tolerance_ratio,
    )
    objective = evaluator.objective
    if (tolerance_ratio is None) != (config.start_temperature_score is None):
        raise ValueError(
            "재통행 모드에서만 start_temperature_score를 함께 지정해야 합니다."
        )
    initial = evaluator.evaluate(initial_ids)
    if initial is None:
        raise ValueError("초기 경유지 순서에 도달 불가능한 구간이 있습니다.")
    current = best = initial
    destroy = _AdaptivePool(("random", "sequence"))
    repair = _AdaptivePool(("greedy", "random_order"))
    rng = Random(config.seed)
    temperature = (
        config.start_temperature_m
        if tolerance_ratio is None
        else config.start_temperature_score
    )
    seen = {initial_ids}
    attempts = accepted = failed = 0
    stop_reason = "iterations"

    for _ in range(config.iterations):
        if objective.is_optimal(best):
            stop_reason = (
                "exact_target" if tolerance_ratio is None else "exact_target_no_overlap"
            )
            break
        if (
            config.max_cost_calls is not None
            and evaluator.cost_calls >= config.max_cost_calls
        ):
            stop_reason = "cost_budget"
            break
        attempts += 1
        d, r = destroy.choose(rng), repair.choose(rng)
        partial = _destroy(
            current.waypoint_ids,
            remove_count,
            destroy.names[d],
            rng,
            start_id == end_id,
        )
        try:
            candidate = _repair(
                partial,
                pool,
                len(initial_ids),
                repair.names[r],
                evaluator,
                rng,
                config.candidate_limit,
            )
        except _CostBudgetExhausted:
            stop_reason = "cost_budget"
            break
        reward = 0.0
        if candidate is None:
            failed += 1
        else:
            delta = objective.score(candidate) - objective.score(current)
            improved = objective.quality(candidate) < objective.quality(current)
            new_best = objective.quality(candidate) < objective.quality(best)
            if new_best:
                best = candidate
            # 완성 조합만 수락한다. 악화 해를 받아도 best는 별도로 보존한다.
            if candidate.waypoint_ids != current.waypoint_ids and _accept(
                delta, temperature, rng
            ):
                if candidate.waypoint_ids not in seen:
                    reward = 6.0 if new_best else (3.0 if improved else 1.0)
                current = candidate
                seen.add(candidate.waypoint_ids)
                accepted += 1
        destroy.scores[d] += reward
        repair.scores[r] += reward
        if attempts % config.segment_length == 0:
            destroy.update(config.reaction_factor)
            repair.update(config.reaction_factor)
        temperature *= config.cooling_rate

    if objective.is_optimal(best):
        stop_reason = (
            "exact_target" if tolerance_ratio is None else "exact_target_no_overlap"
        )
    return ALNSResult(
        best,
        current,
        attempts,
        accepted,
        failed,
        evaluator.evaluated_orders,
        evaluator.cost_calls,
        stop_reason,
        destroy.snapshot(),
        repair.snapshot(),
        evaluator.route_evaluations,
    )
