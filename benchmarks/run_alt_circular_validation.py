"""
benchmarks/run_alt_circular_validation.py

순환 경로 구간 연결 A*에 ALT 휴리스틱을 연결한 변경(#465)의 실그래프 검증 러너.

같은 프로세스·같은 시드에서 ALT를 부착한 경우와 떼어낸 경우로 같은 순환 요청을 각각
만들어 두 가지를 본다.

1. **결과 불변**: 노드열과 거리가 같은가. ALT와 Haversine이 둘 다 admissible하므로
   최적 비용은 같아야 하고, 실제 서울 도보망은 length가 실수값이라 동점이 드물어
   노드열까지 같을 것으로 기대한다.
2. **탐색량·시간**: 큐에서 꺼낸 노드 수(popped)와 A* 순수 시간이 얼마나 줄어드는가.
   popped는 머신 부하와 무관한 결정론적 값이라 시간보다 신뢰할 수 있는 비교 기준이다.
   요청 전체 시간 대비 A*가 차지하는 비중도 함께 찍어, 탐색 개선이 체감으로 이어지는지
   판단할 수 있게 한다.

계측은 `benchmarks/runner/_astar_instrumented.py`의 복제판 A*로 한다. 휴리스틱 선택
로직은 건드리지 않는다 — `PathUtils._search_heuristic()`이 고른 것을 그대로 계측판에
넘기므로, 두 모드 사이의 유일한 차이는 ALT 부착 여부다.

⚠ 점수(safety/accident/slope)는 fixture에 없어 `cost_context`를 주입하지 않는다. 즉 이
러너가 지나가는 것은 **거리 전용 경로**뿐이다. 가중 비용 분기는 합성 그래프 단위
테스트(tests/unit/test_grasp_waypoint_common.py)가 덮으며, 실그래프 검증은 점수 적재와
artifact 재빌드 이후에 가능하다.

실행:
    python -m benchmarks.run_alt_circular_validation
"""

import json
import time
from pathlib import Path

from benchmarks.benchmark import _load_default_graph
from benchmarks.runner._astar_instrumented import astar_path_instrumented
from src.route_engine.alt_runtime import attach_alt_heuristic, prepare_alt_heuristic
from src.route_engine.engines import path_utils as pu
from src.route_engine.engines.circular_grasp_waypoint_alns import CircularGraspWaypointAlnsEngine
from src.route_engine.engines.path_utils import PathUtils
from src.schema.route_schema import CircularRouteInput

DATASET = Path("benchmarks/datasets/route_engine.json")
SCENARIO_COUNT = 8   # route_engine.json의 circular 시나리오 앞에서부터
NUM_WAYPOINTS = 4    # 운영 기본값(GRASP+ALNS, N=4)
ALT_K = 8            # 프로덕션 기본값 WALK_ALT_K

_STATS = {"calls": 0, "time": 0.0, "popped": 0, "pushed": 0}


def _patched_astar_path(self, source, target, weight, min_ratio: float = 1.0):
    """PathUtils.astar_path를 계측판으로 대체한다(이 러너 프로세스 안에서만)."""
    heuristic = self._search_heuristic(min_ratio)
    started = time.perf_counter()
    path, popped, pushed = astar_path_instrumented(
        self.G, source, target, heuristic=heuristic, weight=weight,
    )
    _STATS["time"] += time.perf_counter() - started
    _STATS["calls"] += 1
    _STATS["popped"] += popped
    _STATS["pushed"] += pushed
    return path


def _reset_stats() -> None:
    _STATS.update({"calls": 0, "time": 0.0, "popped": 0, "pushed": 0})


def _run_once(G, start_node: int, target_km: float) -> dict:
    inp = CircularRouteInput(
        start_lat=G.nodes[start_node].get("lat", 0.0),
        start_lon=G.nodes[start_node].get("lon", 0.0),
        target_km=target_km,
    )
    engine = CircularGraspWaypointAlnsEngine(inp, G, num_waypoints=NUM_WAYPOINTS)
    _reset_stats()
    started = time.perf_counter()
    nodes = engine.find_path(start_node, target_km)
    total = time.perf_counter() - started

    pruned = engine.utils.prune_dead_ends(nodes) if nodes and len(nodes) >= 2 else []
    return {
        "nodes": pruned,
        "distance": engine.utils.calc_distance(pruned) if len(pruned) >= 2 else 0.0,
        "total": total,
        "astar_time": _STATS["time"],
        "calls": _STATS["calls"],
        "popped": _STATS["popped"],
        "pushed": _STATS["pushed"],
    }


def _load_cases(G) -> list[tuple[str, int, float]]:
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    utils = PathUtils(G)
    cases = []
    for sc in (s for s in data["scenarios"] if s["mode"] == "circular"):
        if len(cases) >= SCENARIO_COUNT:
            break
        node = utils.find_nearest_node(sc["start_lat"], sc["start_lon"])
        if node is not None:
            cases.append((sc["id"], node, sc["target_km"]))
    return cases


def main() -> int:
    pu.PathUtils.astar_path = _patched_astar_path

    G = _load_default_graph()
    if G is None:
        print("fixture 그래프가 없습니다. 'python -m benchmarks.build_fixtures'로 먼저 생성하세요.")
        return 2
    print(f"그래프: 노드 {G.number_of_nodes():,} / 엣지 {G.number_of_edges():,}")

    started = time.perf_counter()
    heuristic, info = prepare_alt_heuristic(
        G, enabled=True, method="planar", k=ALT_K, seed=0, weight="length",
    )
    if heuristic is None:
        print("ALT 준비에 실패해 비교할 수 없습니다.")
        return 2
    print(f"ALT 준비: {time.perf_counter() - started:.2f}s, "
          f"k_actual={info.k_actual}, 거리표 항목={info.table_entries:,}")

    rows = []
    for case_id, start_node, target_km in _load_cases(G):
        attach_alt_heuristic(G, None, None)        # Haversine
        base = _run_once(G, start_node, target_km)
        attach_alt_heuristic(G, heuristic, info)   # ALT
        alt = _run_once(G, start_node, target_km)
        attach_alt_heuristic(G, None, None)
        rows.append((case_id, base, alt))

        print(
            f"{case_id:>14} target={target_km:>4.1f}km  "
            f"노드열동일={'예' if base['nodes'] == alt['nodes'] else '아니오'}  "
            f"거리 {base['distance']:>8.1f}/{alt['distance']:>8.1f}m  "
            f"popped {base['popped']:>7,}/{alt['popped']:>7,} "
            f"({base['popped'] / max(alt['popped'], 1):.2f}x)  "
            f"A*시간 {base['astar_time']:>6.3f}/{alt['astar_time']:>6.3f}s  "
            f"전체 {base['total']:>6.2f}/{alt['total']:>6.2f}s"
        )

    print("\n=== 합계 ===")
    totals = {}
    for label, idx in (("Haversine", 1), ("ALT", 2)):
        totals[label] = {
            key: sum(row[idx][key] for row in rows)
            for key in ("calls", "popped", "pushed", "astar_time", "total")
        }
        t = totals[label]
        print(f"{label:>10}: A*호출 {t['calls']:,}  popped {t['popped']:,}  pushed {t['pushed']:,}  "
              f"A*시간 {t['astar_time']:.2f}s  전체 {t['total']:.2f}s  "
              f"A*비중 {t['astar_time'] / t['total']:.1%}")

    base_t, alt_t = totals["Haversine"], totals["ALT"]
    identical = sum(1 for _, base, alt in rows if base["nodes"] == alt["nodes"])
    max_diff = max((abs(base["distance"] - alt["distance"]) for _, base, alt in rows), default=0.0)
    print(f"\n노드열 완전 일치: {identical}/{len(rows)}   거리 최대 차이: {max_diff:.6f}m")
    print(f"popped 감소: {base_t['popped'] / max(alt_t['popped'], 1):.2f}x   "
          f"A* 시간 단축: {base_t['astar_time'] / max(alt_t['astar_time'], 1e-9):.2f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
