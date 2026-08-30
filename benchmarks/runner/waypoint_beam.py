"""실제 artifact의 고정 후보 풀에서 거리 전용·재통행 고려 Beam을 비교한다."""

import json
from time import perf_counter

from benchmarks.runner._waypoint_common import (
    argument_parser,
    evaluation_modes,
    prepare_fixture,
    prepare_route_evaluator,
    quality_fields,
)
from src.route_engine.waypoint_beam import beam_search
from src.route_engine.waypoint_evaluation import attach_route_metrics


def main():
    """같은 후보·Beam 폭으로 각 평가 방식을 빈 캐시에서 반복 측정한다."""
    parser = argument_parser(__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats는 1 이상이어야 합니다.")
    modes = evaluation_modes(args, parser)
    graph, start, pool, cost, cached_distance = prepare_fixture(args, parser)
    route = prepare_route_evaluator(graph, args.path_cache_size)
    for tolerance in modes:
        for repeat in range(args.repeats):
            cached_distance.cache_clear()
            route.cache_clear()
            begin = perf_counter()
            result = beam_search(
                candidates=pool,
                cost=cost,
                start_id=start,
                end_id=start,
                target_m=args.target_m,
                waypoint_count=args.waypoint_count,
                beam_width=args.beam_width,
                tolerance_ratio=tolerance,
                evaluate_route=route if tolerance is not None else None,
            )
            elapsed = perf_counter() - begin
            misses = cached_distance.cache_info().misses
            path_calls = route.cache_info().misses
            if not result.orders:
                parser.error("Beam에서 완성 조합을 찾지 못했습니다.")
            # 거리 전용 결과에도 같은 재통행 지표를 붙인다. 이 사후 측정은 검색 시간 밖이다.
            best = attach_route_metrics(result.orders[0], route, start, start)
            if best is None:
                parser.error("최종 경로를 복원할 수 없습니다.")
            print(
                json.dumps(
                    dict(
                        graph_nodes=graph.number_of_nodes(),
                        graph_edges=graph.number_of_edges(),
                        start_id=start,
                        pool_ids=[candidate["node_id"] for candidate in pool],
                        settings=vars(args),
                        repeat=repeat,
                        target_m=args.target_m,
                        best_ids=best.waypoint_ids,
                        distance_m=best.distance_m,
                        best_error_m=best.error_m,
                        beam_seconds=elapsed,
                        cost_calls=result.cost_calls,
                        shortest_path_calls=misses,
                        route_path_calls=path_calls,
                        total_search_path_calls=misses + path_calls,
                        validation_path_calls=route.cache_info().misses - path_calls,
                        route_evaluations=result.route_evaluations,
                        evaluated_candidates=result.evaluated_candidates,
                        **quality_fields(best, args.target_m, tolerance),
                    )
                )
            )


if __name__ == "__main__":
    main()
