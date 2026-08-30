"""저장된 전수 결과와 변경 없는 Beam 실행의 중간 상태를 대조한다."""
# ruff: noqa: E402

import json
import math
import sys
from collections import defaultdict
from itertools import pairwise
from pathlib import Path

from benchmarks.runner.waypoint_overlap_audit import ROOT, Supply, save_json

import networkx as nx

from src.repository.network.graph_artifact_repository import GraphArtifactRepository
from src.route_engine.waypoint_beam import beam_search
from src.route_engine.waypoint_evaluation import WaypointObjective
from src.route_engine.waypoint_types import RouteMetrics, WaypointOrder


def restore(record):
    """저장된 품질값을 비교용 자료형으로 복원한다."""
    return WaypointOrder(
        tuple(record["ids"]),
        record["distance_m"],
        record["error_m"],
        RouteMetrics(record["distance_m"], record["repeated_m"]),
    )


def equivalent(a, b):
    """다른 덧셈 순서의 1e-9m 이하 차이는 진단에서 동점으로 취급한다."""
    return math.isclose(a.error_m, b.error_m, abs_tol=1e-9, rel_tol=0) and math.isclose(
        a.route_metrics.overlap_ratio,
        b.route_metrics.overlap_ratio,
        abs_tol=1e-12,
        rel_tol=0,
    )


def trace_beam(graph, data, width, tol):
    """Python 실행 추적으로 실제 유지 상태를 관측하며 탐색은 변경하지 않는다."""
    supply = Supply(graph, "astar")
    objective = WaypointObjective(data["target_m"], tol)
    catalog = [restore(row) for row in data["orders"]]
    best = min(catalog, key=objective.rank)
    optimal_ids = [o.waypoint_ids for o in catalog if equivalent(o, best)]
    stages = []
    seen_lists = []

    def trace(frame, event, arg):
        """Beam 유지 목록이 교체되는 시점만 기록한다."""
        if frame.f_code is beam_search.__code__ and event in ("line", "return"):
            beam = frame.f_locals.get("beam")
            if beam is not None and not any(beam is old for old in seen_lists):
                seen_lists.append(beam)
                depth = len(beam[0].waypoint_ids) if beam else -1
                ids = [state.waypoint_ids for state in beam]
                stages.append(
                    dict(
                        depth=depth,
                        kept_ids=ids,
                        surviving_optimal_prefixes=[
                            order[:depth]
                            for order in optimal_ids
                            if order[:depth] in ids
                        ],
                    )
                )
        return trace

    previous = sys.gettrace()
    try:
        sys.settrace(trace)
        result = beam_search(
            candidates=data["pool"],
            cost=supply.cost,
            start_id=data["start"],
            end_id=data["end"],
            target_m=data["target_m"],
            waypoint_count=3,
            beam_width=width,
            tolerance_ratio=tol,
            evaluate_route=supply.route,
        )
    finally:
        sys.settrace(previous)
    return dict(
        width=width,
        tolerance=tol,
        global_best_ids=best.waypoint_ids,
        final_ids=result.orders[0].waypoint_ids,
        stages=stages,
    )


def feasible_components(data, tol):
    """1개 제거·재삽입으로 허용 범위 안에서 이동 가능한 연결 성분을 찾는다."""
    orders = [restore(row) for row in data["orders"]]
    feasible = [order for order in orders if order.error_m <= data["target_m"] * tol]
    graph = nx.Graph()
    buckets = defaultdict(list)
    for order in feasible:
        ids = order.waypoint_ids
        graph.add_node(ids)
        for i in range(3):
            buckets[ids[:i] + ids[i + 1 :]].append(ids)
    # 같은 두 점을 남기는 조합은 서로 이동 가능하다. 성분 판정에는 연결 사슬로 충분하다.
    for ids in buckets.values():
        graph.add_edges_from(pairwise(ids))
    objective = WaypointObjective(data["target_m"], tol)
    lookup = {o.waypoint_ids: o for o in feasible}
    result = []
    for component in nx.connected_components(graph):
        best = min((lookup[ids] for ids in component), key=objective.rank)
        result.append(
            dict(
                size=len(component),
                ids=sorted(component),
                best_ids=best.waypoint_ids,
                best_overlap_pct=100 * best.route_metrics.overlap_ratio,
            )
        )
    return result


def main():
    """진단 결과를 별도 파일에 남기고 핵심만 출력한다."""
    folder = Path(sys.argv[1]).resolve()
    graph = GraphArtifactRepository.load(
        ROOT / "artifacts/walk_graph_v1.pkl", expected_data_version="v2-2026-08-25"
    )
    result = {}
    for scenario in ("circular", "oneway"):
        data = json.loads(
            (folder / f"{scenario}_astar_exhaustive.json").read_text(encoding="utf-8")
        )
        traces = [
            trace_beam(graph, data, width, tol)
            for width, tol in ((2, 0.05), (8, 0.05), (2, 0.075))
        ]
        components = feasible_components(data, 0.05)
        result[scenario] = dict(traces=traces, feasible_components_5pct=components)
        print(
            json.dumps(
                dict(
                    scenario=scenario,
                    traces=traces,
                    component_sizes=[c["size"] for c in components],
                )
            ),
            flush=True,
        )
    save_json(folder / "diagnostics.json", result)


if __name__ == "__main__":
    main()
