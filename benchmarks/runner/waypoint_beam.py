"""실제 artifact의 고정 후보 풀에서 경유지 Beam Search만 측정한다."""

import json
from time import perf_counter

from benchmarks.runner._waypoint_common import argument_parser, prepare_fixture
from src.route_engine.waypoint_beam import beam_search


def main():
    """Beam을 빈 거리 캐시에서 반복 실행하고 거리 오차와 계산량을 출력한다."""
    parser = argument_parser(__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats는 1 이상이어야 합니다.")
    graph, start, pool, cost, cached_distance = prepare_fixture(args, parser)
    for repeat in range(args.repeats):
        cached_distance.cache_clear()
        begin = perf_counter()
        result = beam_search(
            candidates=pool,
            cost=cost,
            start_id=start,
            end_id=start,
            target_m=args.target_m,
            waypoint_count=args.waypoint_count,
            beam_width=args.beam_width,
        )
        elapsed = perf_counter() - begin
        misses = cached_distance.cache_info().misses
        if not result.orders:
            parser.error("Beam에서 완성 조합을 찾지 못했습니다.")
        best = result.orders[0]
        stops = (start, *best.waypoint_ids, start)
        actual = sum(cost(a, b) for a, b in zip(stops, stops[1:]))
        assert abs(actual - best.distance_m) < 1e-6
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
                    evaluated_candidates=result.evaluated_candidates,
                )
            )
        )


if __name__ == "__main__":
    main()
