"""동일한 초기 경유지 순서로 거리 전용·재통행 고려 ALNS를 비교한다.

후보 추출·도로 공급자는 검증용이다. 초기 순서를 생략하면 거리 전용 Beam을 사용한다.
"""

import json
from time import perf_counter

from benchmarks.runner._waypoint_common import (
    argument_parser,
    evaluation_modes,
    prepare_fixture,
    prepare_route_evaluator,
    quality_fields,
)
from src.route_engine.waypoint_alns import ALNSConfig, alns_search
from src.route_engine.waypoint_beam import beam_search
from src.route_engine.waypoint_evaluation import WaypointObjective, attach_route_metrics
from src.route_engine.waypoint_types import WaypointOrder


def prepare_initial(args, parser, pool, cost, start):
    """외부 초기 순서를 사용하거나 모든 비교에 공통으로 쓸 Beam 초기 해를 만든다."""
    if args.initial_ids is not None:
        ids = tuple(args.initial_ids)
        if len(set(ids)) != len(ids) or not set(ids) <= {c["node_id"] for c in pool}:
            parser.error(
                "initial-ids는 현재 후보 풀 안의 중복 없는 경유지 ID여야 합니다."
            )
        stops = (start, *ids, start)
        total = sum(cost(a, b) for a, b in zip(stops, stops[1:]))
        return WaypointOrder(ids, total, abs(total - args.target_m))
    beam = beam_search(
        candidates=pool,
        cost=cost,
        start_id=start,
        end_id=start,
        target_m=args.target_m,
        waypoint_count=args.waypoint_count,
        beam_width=args.beam_width,
    )
    if not beam.orders:
        parser.error("Beam에서 초기 조합을 찾지 못했습니다.")
    return beam.orders[0]


def main():
    """같은 초기 해·seed·반복 및 호출 한도로 평가 방식별 품질과 비용을 비교한다."""
    parser = argument_parser(__doc__)
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--cost-budget", type=int, default=20000)
    parser.add_argument("--seeds", nargs="+", type=int, default=[0, 1, 2])
    parser.add_argument("--removal-fraction", type=float, default=0.3)
    parser.add_argument("--start-temperature-m", type=float, default=100.0)
    parser.add_argument(
        "--start-temperature-score",
        type=float,
        help="재통행 비교 모드의 무차원 SA 온도. 0이면 주 점수 악화를 거절한다.",
    )
    parser.add_argument("--cooling-rate", type=float, default=0.99)
    parser.add_argument("--segment-length", type=int, default=20)
    parser.add_argument("--reaction-factor", type=float, default=0.2)
    parser.add_argument("--candidate-limit", type=int)
    parser.add_argument(
        "--initial-ids",
        nargs="+",
        type=int,
        help="출발·도착 제외 초기 경유지 순서. 모든 비교가 이 순서로 시작한다.",
    )
    args = parser.parse_args()
    modes = evaluation_modes(args, parser)
    if bool(args.tolerances) != (args.start_temperature_score is not None):
        parser.error("tolerances와 start-temperature-score를 함께 지정해야 합니다.")
    if args.initial_ids is not None:
        args.waypoint_count = len(args.initial_ids)
    graph, start, pool, cost, cached_distance = prepare_fixture(args, parser)
    route = prepare_route_evaluator(graph, args.path_cache_size)
    initial = attach_route_metrics(
        prepare_initial(args, parser, pool, cost, start), route, start, start
    )
    if initial is None:
        parser.error("초기 경로를 복원할 수 없습니다.")
    for tolerance in modes:
        objective = WaypointObjective(args.target_m, tolerance)
        for seed in args.seeds:
            # 평가 방식과 seed가 달라도 초기 해는 같고, 두 캐시는 모두 비운다.
            cached_distance.cache_clear()
            route.cache_clear()
            begin = perf_counter()
            result = alns_search(
                candidates=pool,
                cost=cost,
                initial_ids=initial.waypoint_ids,
                start_id=start,
                end_id=start,
                target_m=args.target_m,
                tolerance_ratio=tolerance,
                evaluate_route=route if tolerance is not None else None,
                config=ALNSConfig(
                    iterations=args.iterations,
                    max_cost_calls=args.cost_budget,
                    seed=seed,
                    removal_fraction=args.removal_fraction,
                    start_temperature_m=args.start_temperature_m,
                    start_temperature_score=args.start_temperature_score
                    if tolerance is not None
                    else None,
                    cooling_rate=args.cooling_rate,
                    segment_length=args.segment_length,
                    reaction_factor=args.reaction_factor,
                    candidate_limit=args.candidate_limit,
                ),
            )
            elapsed = perf_counter() - begin
            misses = cached_distance.cache_info().misses
            path_calls = route.cache_info().misses
            best = attach_route_metrics(result.best, route, start, start)
            if best is None:
                parser.error("최종 경로를 복원할 수 없습니다.")
            assert objective.quality(best) <= objective.quality(initial)
            print(
                json.dumps(
                    dict(
                        graph_nodes=graph.number_of_nodes(),
                        graph_edges=graph.number_of_edges(),
                        start_id=start,
                        pool_ids=[candidate["node_id"] for candidate in pool],
                        settings=vars(args),
                        seed=seed,
                        target_m=args.target_m,
                        initial_source="provided"
                        if args.initial_ids is not None
                        else "distance_only_beam",
                        initial_ids=initial.waypoint_ids,
                        initial_error_m=initial.error_m,
                        initial_overlap_ratio=initial.route_metrics.overlap_ratio,
                        best_ids=best.waypoint_ids,
                        best_error_m=best.error_m,
                        distance_m=best.distance_m,
                        alns_seconds=elapsed,
                        iterations=result.iterations,
                        cost_calls=result.cost_calls,
                        shortest_path_calls=misses,
                        route_path_calls=path_calls,
                        total_search_path_calls=misses + path_calls,
                        validation_path_calls=route.cache_info().misses - path_calls,
                        route_evaluations=result.route_evaluations,
                        stop_reason=result.stop_reason,
                        **quality_fields(best, args.target_m, tolerance),
                    )
                )
            )


if __name__ == "__main__":
    main()
