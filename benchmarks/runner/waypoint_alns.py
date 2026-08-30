"""실제 artifact의 작은 고정 후보 풀로 Beam → ALNS 연결을 검증한다.

여기의 후보 추출·거리 공급자는 검증용이며 실제 후보 생성 모듈을 대체하지 않는다.
"""

import json
from time import perf_counter

from benchmarks.runner._waypoint_common import argument_parser, prepare_fixture
from src.route_engine.waypoint_alns import ALNSConfig, alns_search
from src.route_engine.waypoint_beam import beam_search


def main():
    """동일한 초기 해와 빈 거리 캐시에서 seed별 ALNS 성능을 측정한다."""
    parser = argument_parser(__doc__)
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--cost-budget", type=int, default=20000)
    parser.add_argument("--seeds", nargs="+", type=int, default=[0, 1, 2])
    parser.add_argument("--removal-fraction", type=float, default=0.3)
    parser.add_argument("--start-temperature-m", type=float, default=100.0)
    parser.add_argument("--cooling-rate", type=float, default=0.99)
    parser.add_argument("--segment-length", type=int, default=20)
    parser.add_argument("--reaction-factor", type=float, default=0.2)
    parser.add_argument("--candidate-limit", type=int)
    args = parser.parse_args()
    graph, start, pool, cost, cached_distance = prepare_fixture(args, parser)
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
    initial = beam.orders[0]
    for seed in args.seeds:
        # 모든 seed를 같은 초기 해와 빈 거리 캐시에서 시작한다.
        cached_distance.cache_clear()
        begin = perf_counter()
        result = alns_search(
            candidates=pool,
            cost=cost,
            initial_ids=initial.waypoint_ids,
            start_id=start,
            end_id=start,
            target_m=args.target_m,
            config=ALNSConfig(
                iterations=args.iterations,
                max_cost_calls=args.cost_budget,
                seed=seed,
                removal_fraction=args.removal_fraction,
                start_temperature_m=args.start_temperature_m,
                cooling_rate=args.cooling_rate,
                segment_length=args.segment_length,
                reaction_factor=args.reaction_factor,
                candidate_limit=args.candidate_limit,
            ),
        )
        elapsed = perf_counter() - begin
        misses = cached_distance.cache_info().misses
        assert result.best.error_m <= initial.error_m
        stops = (start, *result.best.waypoint_ids, start)
        actual = sum(cost(a, b) for a, b in zip(stops, stops[1:]))
        assert abs(actual - result.best.distance_m) < 1e-6
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
                    initial_ids=initial.waypoint_ids,
                    initial_error_m=initial.error_m,
                    best_ids=result.best.waypoint_ids,
                    best_error_m=result.best.error_m,
                    distance_m=result.best.distance_m,
                    alns_seconds=elapsed,
                    iterations=result.iterations,
                    cost_calls=result.cost_calls,
                    shortest_path_calls=misses,
                    stop_reason=result.stop_reason,
                )
            )
        )


if __name__ == "__main__":
    main()
