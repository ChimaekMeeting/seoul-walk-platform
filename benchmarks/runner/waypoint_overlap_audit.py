"""Artifact 기반 경유지 전수 비교 실행기. 서비스 및 알고리즘 파일은 변경하지 않는다."""
# ruff: noqa: E402

from __future__ import annotations

import hashlib
import json
import math
import platform
import statistics
import sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from functools import lru_cache
from itertools import combinations, permutations
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import networkx as nx

from src.repository.network.graph_artifact_repository import GraphArtifactRepository
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.waypoint_alns import ALNSConfig, alns_search
from src.route_engine.waypoint_beam import beam_search
from src.route_engine.waypoint_evaluation import RouteEvaluator, WaypointObjective
from src.route_engine.waypoint_types import WaypointOrder

TOLS = (None, 0.025, 0.05, 0.075)
STATIONS = {
    "gyeongbokgung": (37.57567, 126.97358),
    "seodaemun": (37.56577, 126.96649),
    "jonggak": (37.57017, 126.98308),
}


def save_json(path, data):
    """이번 실행의 새 산출물만 저장하고 기존 파일 덮어쓰기를 거부한다."""
    with path.open("x", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)


def digest(path):
    """재현에 사용한 파일 내용을 SHA256으로 식별한다."""
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def percentile(values, fraction):
    """정렬된 측정값에서 nearest-rank 분위수를 구한다."""
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def sample_pool(graph, start, end, target):
    """출발지 target/2 영역을 거리순 균등 표본추출한다. 편도에서는 임시 진단 풀이다."""
    distances = nx.single_source_dijkstra_path_length(
        graph, start, cutoff=target / 2, weight="length"
    )
    ids = sorted(
        (node for node in distances if node not in (start, end)),
        key=lambda node: (distances[node], node),
    )
    assert len(ids) >= 12
    selected = [ids[i * (len(ids) - 1) // 11] for i in range(12)]
    pool = [
        dict(node_id=n, lat=graph.nodes[n]["lat"], lon=graph.nodes[n]["lon"])
        for n in selected
    ]
    return pool, len(ids)


class Supply:
    """분리된 거리·경로 캐시로 고정 그래프의 구간을 공급한다."""

    def __init__(self, graph, connector):
        """구간 연결 방식과 별도의 Dijkstra 거리 공급자를 준비한다."""
        self.graph = graph
        self.connector = connector
        self.utils = PathUtils(graph)
        self.paths = lru_cache(maxsize=1024)(self._path)
        self.distances = lru_cache(maxsize=1024)(self._distance)
        self.route = RouteEvaluator(self.path, self.edge_length, cache_size=1024)

    def edge_length(self, a, b):
        """거리 누락 시 실패하며 기본 길이로 대체하지 않는다."""
        return self.graph[a][b]["length"]

    def _distance(self, a, b):
        """방향을 정규화한 쌍의 Dijkstra 최단거리를 계산한다."""
        return nx.shortest_path_length(self.graph, a, b, weight="length")

    def cost(self, a, b):
        """기존 대칭 cost 계약으로 미터 단위 최단거리를 반환한다."""
        return self.distances(min(a, b), max(a, b))

    def _path(self, a, b):
        """canonical 방향의 실제 도로 노드열을 재방문 페널티 없이 찾는다."""
        if self.connector == "astar":
            return tuple(self.utils.astar_path(a, b, weight="length"))
        return tuple(nx.shortest_path(self.graph, a, b, weight="length"))

    def path(self, a, b):
        """동일 노드 쌍의 역방향에는 캐시된 노드열을 뒤집어 사용한다."""
        nodes = self.paths(min(a, b), max(a, b))
        return nodes if a <= b else nodes[::-1]

    def nodes(self, stops):
        """구간 접합점만 한 번 기록하며 재통행 도로는 그대로 남긴다."""
        nodes = [stops[0]]
        for a, b in zip(stops, stops[1:]):
            nodes.extend(self.path(a, b)[1:])
        return nodes

    def order(self, ids, start, end, target):
        """구간 거리 합과 실제 경로 평가 결과를 교차 검증한다."""
        stops = (start, *ids, end)
        length = sum(self.cost(a, b) for a, b in zip(stops, stops[1:]))
        metrics = self.route(stops)
        assert math.isclose(length, metrics.distance_m, abs_tol=1e-6, rel_tol=1e-9)
        return WaypointOrder(tuple(ids), length, abs(length - target), metrics)

    def verify(self, order, start, end):
        """Counter를 사용한 별도 계산으로 연결성·총거리·추가 통행 거리를 검증한다."""
        nodes = self.nodes((start, *order.waypoint_ids, end))
        assert nodes[0] == start and nodes[-1] == end
        edges = Counter(tuple(sorted((a, b))) for a, b in zip(nodes, nodes[1:]))
        total = math.fsum(
            count * self.edge_length(*edge) for edge, count in edges.items()
        )
        repeated = math.fsum(
            (count - 1) * self.edge_length(*edge) for edge, count in edges.items()
        )
        assert math.isclose(total, order.distance_m, abs_tol=1e-6)
        assert math.isclose(repeated, order.route_metrics.repeated_m, abs_tol=1e-6)
        return nodes

    def clear(self):
        """독립 실행 전에 거리·경로·평가 캐시를 모두 비운다."""
        self.paths.cache_clear()
        self.distances.cache_clear()
        self.route.cache_clear()


def fields(order):
    """JSON과 표에서 공통으로 사용할 경로 품질을 추출한다."""
    return dict(
        ids=order.waypoint_ids,
        distance_m=order.distance_m,
        error_m=order.error_m,
        repeated_m=order.route_metrics.repeated_m,
        overlap_pct=100 * order.route_metrics.overlap_ratio,
    )


def independent_key(order, target, tol):
    """제품 평가 함수를 호출하지 않고 같은 명세를 독립 계산한다."""
    error = order.error_m / target
    if tol is None:
        return order.error_m, 0.0, order.waypoint_ids
    overlap = order.route_metrics.overlap_ratio
    if order.error_m <= target * tol:
        return overlap, error, order.waypoint_ids
    return 1 + error, overlap, order.waypoint_ids


def exhaustive(supply, pool, start, end, target):
    """후보 12개에서 경유지 3개의 1320개 순서를 모두 평가한다."""
    catalog = {}
    for ids in permutations([p["node_id"] for p in pool], 3):
        order = supply.order(ids, start, end, target)
        supply.verify(order, start, end)
        catalog[ids] = order
    assert len(catalog) == 1320
    summaries = []
    for tol in TOLS:
        objective = WaypointObjective(target, tol)
        best = min(
            catalog.values(), key=lambda item: independent_key(item, target, tol)
        )
        for order in catalog.values():
            assert objective.rank(order) == independent_key(order, target, tol)
        feasible = (
            None
            if tol is None
            else sum(o.error_m <= target * tol for o in catalog.values())
        )
        summaries.append(dict(tolerance=tol, feasible_orders=feasible, **fields(best)))
    return catalog, summaries


def run_searches(graph, pool, start, end, target, catalog):
    """동일 풀에서 Beam 폭 및 ALNS seed를 비교하고 best 반환을 검증한다."""
    supply = Supply(graph, "astar")
    common = dict(
        candidates=pool, cost=supply.cost, start_id=start, end_id=end, target_m=target
    )
    runs = []
    initial = None
    for width in (2, 8, 1320):
        for tol in TOLS:
            supply.clear()
            begin = perf_counter()
            result = beam_search(
                **common,
                waypoint_count=3,
                beam_width=width,
                tolerance_ratio=tol,
                evaluate_route=supply.route if tol is not None else None,
            )
            seconds = perf_counter() - begin
            counts = dict(
                distance_search_calls=supply.distances.cache_info().misses,
                astar_calls=supply.paths.cache_info().misses,
            )
            assert result.orders
            best = catalog[result.orders[0].waypoint_ids]
            assert math.isclose(
                best.distance_m, result.orders[0].distance_m, abs_tol=1e-6
            )
            if width == 2 and tol is None:
                initial = best
            objective = WaypointObjective(target, tol)
            exact = min(catalog.values(), key=objective.rank)
            optimal = objective.quality(best) == objective.quality(exact)
            if width == 1320:
                assert optimal
            runs.append(
                dict(
                    algorithm="beam",
                    width=width,
                    tolerance=tol,
                    seconds=seconds,
                    cost_calls=result.cost_calls,
                    optimal=optimal,
                    **counts,
                    **fields(best),
                )
            )
    assert initial is not None
    for tol in TOLS:
        objective = WaypointObjective(target, tol)
        exact = min(catalog.values(), key=objective.rank)
        for seed in range(10):
            supply.clear()
            observed = set()

            def observe(stops):
                """외부 평가 공급자에서 완성 길이 후보 방문을 기록한다. 탐색은 변경하지 않는다."""
                if len(stops) == 5:
                    observed.add(tuple(stops[1:-1]))
                return supply.route(stops)

            config = ALNSConfig(
                iterations=200,
                max_cost_calls=20000,
                seed=seed,
                start_temperature_score=0.05 if tol is not None else None,
            )
            begin = perf_counter()
            result = alns_search(
                **common,
                initial_ids=initial.waypoint_ids,
                config=config,
                tolerance_ratio=tol,
                evaluate_route=observe if tol is not None else None,
            )
            seconds = perf_counter() - begin
            counts = dict(
                distance_search_calls=supply.distances.cache_info().misses,
                astar_calls=supply.paths.cache_info().misses,
            )
            best = catalog[result.best.waypoint_ids]
            current = catalog[result.current.waypoint_ids]
            assert math.isclose(best.distance_m, result.best.distance_m, abs_tol=1e-6)
            assert objective.quality(best) <= objective.quality(initial)
            catalog_comparison_disagrees = objective.quality(best) > objective.quality(
                current
            )
            if catalog_comparison_disagrees:
                print(
                    json.dumps(
                        dict(
                            stage="comparison_diagnostic",
                            tolerance=tol,
                            seed=seed,
                            raw_best=asdict(result.best),
                            raw_current=asdict(result.current),
                            catalog_best=asdict(best),
                            catalog_current=asdict(current),
                        )
                    ),
                    flush=True,
                )
            if tol is not None:
                assert objective.quality(result.best) <= objective.quality(
                    result.current
                )
            else:
                assert result.best.error_m <= result.current.error_m
            better_observed = [
                ids
                for ids in observed
                if objective.quality(catalog[ids]) < objective.quality(best)
            ]
            runs.append(
                dict(
                    algorithm="alns",
                    tolerance=tol,
                    seed=seed,
                    config=asdict(config),
                    seconds=seconds,
                    cost_calls=result.cost_calls,
                    iterations=result.iterations,
                    stop_reason=result.stop_reason,
                    accepted_moves=result.accepted_moves,
                    current=fields(current),
                    initial=fields(initial),
                    catalog_comparison_disagrees=catalog_comparison_disagrees,
                    complete_evaluated_ids=sorted(observed),
                    better_evaluated_than_returned=better_observed,
                    optimal=objective.quality(best) == objective.quality(exact),
                    **counts,
                    **fields(best),
                )
            )
        latest = runs[-10:]
        print(
            json.dumps(
                dict(
                    stage="alns",
                    target=target,
                    tolerance=tol,
                    overlap_min=min(r["overlap_pct"] for r in latest),
                    overlap_median=statistics.median(r["overlap_pct"] for r in latest),
                    overlap_max=max(r["overlap_pct"] for r in latest),
                    seed0=fields(catalog[tuple(latest[0]["ids"])]),
                ),
                ensure_ascii=False,
            ),
            flush=True,
        )
    return runs


def shortest_check(graph, start, end):
    """동일 역 노드에서 Dijkstra와 A*를 번갈아 실행해 거리와 시간을 확인한다."""
    utils = PathUtils(graph)
    timings = {"dijkstra": [], "astar": []}
    results = {}
    for iteration in range(33):
        for name in (
            ("dijkstra", "astar") if iteration % 2 == 0 else ("astar", "dijkstra")
        ):
            begin = perf_counter()
            nodes = (
                nx.dijkstra_path(graph, start, end, weight="length")
                if name == "dijkstra"
                else utils.astar_path(start, end, weight="length")
            )
            elapsed = perf_counter() - begin
            assert nodes[0] == start and nodes[-1] == end
            length = math.fsum(graph[a][b]["length"] for a, b in zip(nodes, nodes[1:]))
            results[name] = dict(distance_m=length, nodes=nodes)
            if iteration >= 3:
                timings[name].append(elapsed)
    assert math.isclose(
        results["dijkstra"]["distance_m"], results["astar"]["distance_m"], abs_tol=1e-6
    )
    for name in timings:
        results[name].update(
            samples_seconds=timings[name],
            p50_seconds=statistics.median(timings[name]),
            p95_seconds=percentile(timings[name], 0.95),
        )
    return dict(warmup_per_algorithm=3, repetitions_per_algorithm=30, results=results)


def main():
    """새 실행 폴더에 설정·전수 비교·탐색 결과·도로 노드열을 저장한다."""
    output = (
        ROOT
        / "tmp/waypoint_overlap_validation"
        / datetime.now().strftime("run_%Y%m%d_%H%M%S")
    )
    output.mkdir(parents=True, exist_ok=False)
    artifact = ROOT / "artifacts/walk_graph_v1.pkl"
    graph = GraphArtifactRepository.load(
        artifact, expected_data_version="v2-2026-08-25"
    )
    assert all(
        math.isfinite(data["length"]) and data["length"] >= 0
        for _, _, data in graph.edges(data=True)
    )
    utils = PathUtils(graph)
    stations = {}
    for name, (lat, lon) in STATIONS.items():
        node = utils.find_nearest_node_with_expansion(lat, lon)
        assert node is not None
        data = graph.nodes[node]
        stations[name] = dict(
            input_lat=lat,
            input_lon=lon,
            node_id=node,
            snapped_lat=data["lat"],
            snapped_lon=data["lon"],
            snap_m=utils._haversine_m(lat, lon, data["lat"], data["lon"]),
        )
    metadata = dict(
        python=platform.python_version(),
        networkx=nx.__version__,
        artifact_sha256=digest(artifact),
        graph_nodes=graph.number_of_nodes(),
        graph_edges=graph.number_of_edges(),
        stations=stations,
        station_source="User supplied screenshots; not independently sourced station entrance coordinates",
        previous_runner_available=False,
        waypoint_count=3,
        alns_seeds=list(range(10)),
        alns_iterations=200,
        max_cost_calls=20000,
        temperature_score=0.05,
        pool_rule="distance-sorted quantile sample of 12 within target/2 of start; exclude start/end",
        oneway_pool_status="new diagnostic fixture, not validated team oneway candidate generator",
        cold_cache_timing=True,
        no_revisit_penalty=True,
        code_sha256={
            p: digest(ROOT / p)
            for p in (
                "src/route_engine/waypoint_beam.py",
                "src/route_engine/waypoint_alns.py",
                "src/route_engine/waypoint_evaluation.py",
                "src/route_engine/engines/path_utils.py",
            )
        },
    )
    save_json(output / "metadata.json", metadata)
    start = stations["gyeongbokgung"]["node_id"]
    save_json(
        output / "shortest.json",
        shortest_check(graph, start, stations["seodaemun"]["node_id"]),
    )
    print(
        json.dumps(dict(stage="start", output=str(output), stations=stations)),
        flush=True,
    )
    for name, end, target in (
        ("circular", start, 4000.0),
        ("oneway", stations["jonggak"]["node_id"], 3000.0),
    ):
        pool, population = sample_pool(graph, start, end, target)
        catalog = None
        path_sets = {}
        for connector in ("shortest_path", "astar"):
            supply = Supply(graph, connector)
            begin = perf_counter()
            current, summaries = exhaustive(supply, pool, start, end, target)
            elapsed = perf_counter() - begin
            print(
                json.dumps(
                    dict(
                        stage="exhaustive",
                        scenario=name,
                        connector=connector,
                        seconds=elapsed,
                        pool_ids=[p["node_id"] for p in pool],
                        results=summaries,
                    )
                ),
                flush=True,
            )
            legs = {
                f"{a},{b}": list(supply.path(a, b))
                for a, b in combinations(
                    sorted({start, end, *(p["node_id"] for p in pool)}), 2
                )
            }
            path_sets[connector] = legs
            save_json(
                output / f"{name}_{connector}_exhaustive.json",
                dict(
                    scenario=name,
                    start=start,
                    end=end,
                    target_m=target,
                    pool=pool,
                    cutoff_population=population,
                    connector=connector,
                    seconds=elapsed,
                    summary=summaries,
                    orders=[fields(o) for o in current.values()],
                    canonical_legs=legs,
                ),
            )
            if connector == "astar":
                catalog = current
        assert catalog is not None
        mismatch = [
            pair
            for pair, nodes in path_sets["astar"].items()
            if nodes != path_sets["shortest_path"][pair]
        ]
        runs = run_searches(graph, pool, start, end, target, catalog)
        supply = Supply(graph, "astar")
        selected_paths = {}
        for ids in {tuple(run["ids"]) for run in runs}:
            selected_paths[",".join(map(str, ids))] = supply.verify(
                catalog[ids], start, end
            )
        save_json(
            output / f"{name}_searches.json",
            dict(
                scenario=name,
                target_m=target,
                pool=pool,
                start=start,
                end=end,
                path_tie_differences=mismatch,
                runs=runs,
                selected_paths=selected_paths,
            ),
        )
    print("COMPLETE " + str(output), flush=True)


if __name__ == "__main__":
    main()
