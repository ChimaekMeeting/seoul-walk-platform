"""편도 점대점 최단거리: Dijkstra / Haversine A* / ALT 4종 비교 러너.

같은 (출발, 도착) 쌍에 같은 weight를 주고 휴리스틱만 바꿔가며, 탐색이 노드를 몇 개나
확장했는지(popped)와 얼마나 걸렸는지를 잰다. 비교 대상 6종:

    dijkstra   기준선. nx.shortest_path(method="dijkstra").
    haversine  프로덕션 OnewayAstarEngine._heuristic과 같은 직선거리 휴리스틱.
    random     landmark_random.select_landmarks_random
    farthest   landmark_farthest.select_landmarks_farthest
    planar     landmark_planar.select_landmarks_planar (n_sectors=k)
    avoid      landmark_avoid.select_landmarks_avoid

이 러너는 측정만 한다 — 어느 방식을 채택할지는 판단하지 않는다. src/ 아래 코드는
읽기만 하고 바꾸지 않으며, 어떤 엔진·API에도 연결하지 않는다.

측정 정의(자세한 설명은 docs/route_engine/README.md "A*·ALT 점대점 벤치마크" 절):
  - popped/pushed: _astar_instrumented.astar_path_instrumented가 센 힙 pop/push 횟수.
    dijkstra 행의 popped/pushed는 h=0으로 돌린 같은 계측판에서 잰다(A* with h=0 ==
    Dijkstra). 시간은 스펙대로 nx.shortest_path(method="dijkstra")로 재므로, dijkstra
    행의 시간과 확장 노드 수는 서로 다른 구현에서 나온 값이다.
  - 시간: 계측 없는 탐색을 warmup 1회 + --repeats회 반복한 평균/중앙값/최대(초).
    test_oneway_shortest_path.time_repeated와 같은 방식으로 측정 중 gc를 끈다.
  - select_s/table_s: 랜드마크 선정 시간과 거리표(precompute_landmark_distances) 시간.
    (방식, k, seed) 조합당 전체 실행에서 1회만 하고 모든 시나리오가 재사용한다.
  - table_entries/table_bytes: 거리표의 총 항목 수(모든 랜드마크 행의 노드 수 합)와
    pickle.dumps 바이트 수.

weight는 벤치마크 전 구간에서 test_oneway_shortest_path.distance_weight 하나로 고정한다.
랜드마크 선정·거리표·admissibility 검증에도 같은 함수를 넘긴다 — 거리표를 다른 weight로
만들면 삼각부등식 하한이 탐색 비용의 하한이 아니게 되어 admissibility가 깨질 수 있다.

실행:
    python -m benchmarks.runner.alt_shortest_path --k 4 8 16 --seeds 0 1 2 --repeats 5
"""

import argparse
import csv
import gc
import hashlib
import json
import pickle
import statistics
from datetime import datetime
from pathlib import Path
from time import perf_counter

import networkx as nx

from benchmarks.config import DATASETS_DIR, RESULTS_DIR
from benchmarks.run_metadata import save_run_metadata
from benchmarks.runner._astar_instrumented import astar_path_instrumented
from benchmarks.runner.test_oneway_shortest_path import distance_weight, path_cost
from src.repository.network.graph_artifact_repository import GraphArtifactRepository
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.landmark_avoid import select_landmarks_avoid
from src.route_engine.landmark_farthest import select_landmarks_farthest
from src.route_engine.landmark_planar import select_landmarks_planar
from src.route_engine.landmark_random import select_landmarks_random
from src.route_engine.landmark_shared import (
    alt_heuristic,
    precompute_landmark_distances,
    verify_admissible,
)

# ALT 선택법 중 seed를 받는 것들. planar는 좌표 결정론이라 seed가 없다.
_SEEDED_ALT = ("random", "farthest", "avoid")

# --methods 없이 돌리면 전부 잰다. 순서는 전처리가 싼 것부터다.
ALL_METHODS = ("dijkstra", "haversine", "random", "farthest", "planar", "avoid")

CSV_COLUMNS = [
    "scenario_id",
    "tier",
    "method",
    "k_requested",
    "k_actual",
    "seed",
    "straight_m",
    "dijkstra_m",
    "path_m",
    "cost_match",
    "path_valid",
    "popped",
    "pushed",
    "search_mean_s",
    "search_median_s",
    "search_max_s",
    "select_s",
    "table_s",
    "table_entries",
    "table_bytes",
    "alt_violations",
    "haversine_violations",
    "status",
]

# 결과 비용이 Dijkstra와 같다고 볼 허용 오차(m).
_COST_TOL_M = 1e-6

# 이 실행의 수치를 좌우하는 소스. run_metadata의 _TRACKED_SOURCES는 순환 경로 격자용이라
# 랜드마크 모듈을 담지 않아, 여기서 따로 해시를 떠서 extra로 넘긴다.
_TRACKED_SOURCES = (
    "benchmarks/build_shortest_path_scenarios.py",
    "benchmarks/runner/alt_shortest_path.py",
    "benchmarks/runner/_astar_instrumented.py",
    "src/route_engine/landmark_shared.py",
    "src/route_engine/landmark_random.py",
    "src/route_engine/landmark_farthest.py",
    "src/route_engine/landmark_planar.py",
    "src/route_engine/landmark_avoid.py",
)

_ROOT = Path(__file__).resolve().parents[2]


def _zero_heuristic(u, v) -> float:
    """h=0. A*를 Dijkstra와 같은 탐색으로 만든다(popped/pushed 비교 기준선)."""
    return 0.0


def haversine_heuristic(graph: nx.Graph):
    """프로덕션 OnewayAstarEngine._heuristic과 같은 공식(PathUtils._haversine_m)."""

    def heuristic(u, v):
        nu, nv = graph.nodes[u], graph.nodes[v]
        return PathUtils._haversine_m(
            nu.get("lat", 0), nu.get("lon", 0), nv.get("lat", 0), nv.get("lon", 0)
        )

    return heuristic


def iter_configs(
    ks: list[int], seeds: list[int], methods: list[str] | None = None
) -> list[dict]:
    """측정할 (방식, k, seed) 조합 목록. 전처리가 싼 것부터 나열한다.

    methods를 주면 그 방식만 남긴다(나열 순서는 methods의 순서가 아니라 위 고정
    순서를 따른다). None이면 ALL_METHODS 전부를 잰다.
    """
    selected = None if methods is None else set(methods)

    def wanted(method: str) -> bool:
        return selected is None or method in selected

    configs = [
        {"method": method, "k": None, "seed": None}
        for method in ("dijkstra", "haversine")
        if wanted(method)
    ]
    for k in ks:
        if wanted("planar"):
            # Planar는 좌표만으로 결정되므로 seed 축이 없다 — k마다 1회.
            configs.append({"method": "planar", "k": k, "seed": None})
        for method in _SEEDED_ALT:
            if not wanted(method):
                continue
            for seed in seeds:
                configs.append({"method": method, "k": k, "seed": seed})
    return configs


def select_landmarks(method: str, graph: nx.Graph, k: int, seed: int | None, weight_fn):
    """방식별 랜드마크 선정. planar만 n_sectors 의미의 k를 받고 seed를 쓰지 않는다."""
    if method == "random":
        return select_landmarks_random(graph, k, seed=seed)
    if method == "farthest":
        return select_landmarks_farthest(graph, k, weight=weight_fn, seed=seed)
    if method == "avoid":
        return select_landmarks_avoid(graph, k, weight=weight_fn, seed=seed)
    if method == "planar":
        return select_landmarks_planar(graph, k)
    raise ValueError(f"랜드마크 선택법이 아닙니다: {method}")


def prepare_config(config: dict, graph: nx.Graph, weight_fn, pairs: list[tuple]) -> dict:
    """조합 1개의 전처리를 1회만 수행한다. 모든 시나리오가 이 결과를 재사용한다.

    dijkstra/haversine은 랜드마크가 없으므로 빈 거리표로 verify_admissible을 돌린다 —
    alt_heuristic이 항상 0을 돌려줘 alt_violations는 0이고, haversine_violations만
    의미가 있다(모든 조합에서 같은 값이 나와야 하는 교차 확인용).
    """
    method = config["method"]
    prepared = {
        "k_actual": None,
        "select_s": None,
        "table_s": None,
        "table_entries": None,
        "table_bytes": None,
        "landmarks": None,
        "table": {},
    }

    if method in ("dijkstra", "haversine"):
        prepared["heuristic"] = None if method == "dijkstra" else haversine_heuristic(graph)
    else:
        t0 = perf_counter()
        landmarks = select_landmarks(method, graph, config["k"], config["seed"], weight_fn)
        prepared["select_s"] = perf_counter() - t0

        t0 = perf_counter()
        table = precompute_landmark_distances(graph, landmarks, weight=weight_fn)
        prepared["table_s"] = perf_counter() - t0

        prepared["k_actual"] = len(landmarks)
        prepared["landmarks"] = [int(n) for n in landmarks]
        prepared["table_entries"] = sum(len(row) for row in table.values())
        prepared["table_bytes"] = len(pickle.dumps(table))
        prepared["table"] = table
        prepared["heuristic"] = lambda u, v: alt_heuristic(table, u, v)

    try:
        report = verify_admissible(graph, prepared["table"], weight=weight_fn, pairs=pairs)
    except ValueError:
        # pairs가 전부 도달 불가면 verify_admissible이 거부한다(landmark_shared.py).
        # 위반 수를 잴 표본이 아예 없다는 뜻이라 None으로 남긴다 — 0으로 적으면
        # "검사했는데 위반이 없었다"로 잘못 읽힌다.
        prepared["alt_violations"] = None
        prepared["haversine_violations"] = None
        prepared["checked_pairs"] = 0
    else:
        prepared["alt_violations"] = report.alt_violations
        prepared["haversine_violations"] = report.haversine_violations
        prepared["checked_pairs"] = report.checked_pairs
    return prepared


def time_search(fn, repeats: int):
    """warmup 1회 + repeats회 반복 측정(초).

    test_oneway_shortest_path.time_repeated와 같은 방식으로 측정 중 gc를 끈다. 그 함수는
    ms 단위의 평균/표준편차/CV만 돌려줘 중앙값·최댓값을 낼 수 없어, 같은 구조로 raw
    시간을 모으는 함수를 따로 뒀다.

    Returns:
        (결과, NetworkXNoPath 예외 또는 None, [초]) — 경로가 없어도 예외로 중단하지
        않고 마지막 시도의 예외 객체를 돌려준다(실패한 탐색의 계산량도 기록해야 한다).
    """
    times: list[float] = []
    result = None
    failure = None
    gc.disable()
    try:
        for i in range(repeats + 1):
            t0 = perf_counter()
            try:
                result = fn()
                failure = None
            except nx.NetworkXNoPath as exc:
                result = None
                failure = exc
            elapsed = perf_counter() - t0
            if i >= 1:  # warmup 1회 제외
                times.append(elapsed)
    finally:
        gc.enable()
    return result, failure, times


def path_is_valid(graph: nx.Graph, path: list, start, end) -> bool:
    """끝점이 맞고 이웃한 노드끼리 실제로 간선으로 이어져 있는지."""
    if not path or path[0] != start or path[-1] != end:
        return False
    return all(graph.has_edge(path[i], path[i + 1]) for i in range(len(path) - 1))


def run_scenario(graph, scenario, config, prepared, weight_fn, repeats, baseline) -> dict:
    """시나리오 1개 × 조합 1개를 측정해 CSV 행 하나를 만든다."""
    method = config["method"]
    start = scenario["start"]["node_id"]
    end = scenario["end"]["node_id"]
    heuristic = prepared["heuristic"]

    if method == "dijkstra":
        def search():
            return nx.shortest_path(graph, start, end, weight=weight_fn, method="dijkstra")
    else:
        def search():
            return astar_path_instrumented(
                graph, start, end, heuristic=heuristic, weight=weight_fn
            )[0]

    result, failure, times = time_search(search, repeats)

    # 확장 노드 수는 계측판으로 따로 한 번 더 잰다(시간 측정에는 섞지 않는다).
    counter_heuristic = _zero_heuristic if method == "dijkstra" else heuristic
    try:
        counted_path, popped, pushed = astar_path_instrumented(
            graph, start, end, heuristic=counter_heuristic, weight=weight_fn
        )
    except nx.NetworkXNoPath as exc:
        counted_path, popped, pushed = None, exc.popped, exc.pushed

    baseline_m = baseline.get(scenario["id"])
    if failure is not None or result is None:
        status = "no_path"
        path_m = None
        # 기준선도 경로 없음이면 "일치"로 본다 — 두 방식의 결론이 같다는 뜻.
        cost_match = baseline_m is None
        valid = baseline_m is None
    else:
        status = "ok"
        path_m = path_cost(graph, result, weight_fn)
        cost_match = baseline_m is not None and abs(path_m - baseline_m) <= _COST_TOL_M
        valid = path_is_valid(graph, result, start, end)
        if counted_path is not None and method != "dijkstra" and counted_path != result:
            # 계측판과 실측판의 경로가 다르면 popped/pushed를 그 경로에 붙여 읽으면 안 된다.
            status = "ok_path_differs_from_counter"

    return {
        "scenario_id": scenario["id"],
        "tier": scenario["tier"],
        "method": method,
        "k_requested": config["k"],
        "k_actual": prepared["k_actual"],
        "seed": config["seed"],
        "straight_m": round(scenario["straight_m"], 3),
        "dijkstra_m": None if baseline_m is None else round(baseline_m, 6),
        "path_m": None if path_m is None else round(path_m, 6),
        "cost_match": cost_match,
        "path_valid": valid,
        "popped": popped,
        "pushed": pushed,
        "search_mean_s": statistics.mean(times),
        "search_median_s": statistics.median(times),
        "search_max_s": max(times),
        "select_s": prepared["select_s"],
        "table_s": prepared["table_s"],
        "table_entries": prepared["table_entries"],
        "table_bytes": prepared["table_bytes"],
        "alt_violations": prepared["alt_violations"],
        "haversine_violations": prepared["haversine_violations"],
        "status": status,
    }


def build_summary(rows: list[dict], configs: list[dict]) -> dict:
    """tier×method별 popped 중앙값·search_median_s 중앙값·cost_match 비율."""
    buckets: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        buckets.setdefault((row["tier"], row["method"]), []).append(row)

    by_tier_method = []
    for (tier, method), group in sorted(buckets.items()):
        by_tier_method.append(
            {
                "tier": tier,
                "method": method,
                "rows": len(group),
                "popped_median": statistics.median(r["popped"] for r in group),
                "search_median_s_median": statistics.median(
                    r["search_median_s"] for r in group
                ),
                "cost_match_ratio": sum(1 for r in group if r["cost_match"]) / len(group),
            }
        )
    return {
        "by_tier_method": by_tier_method,
        "configs": configs,
        "note": "이 입력(시나리오 데이터셋·그래프·머신)에서의 관측이며 고정 기대값이 아니다. "
        "popped/search_median_s 중앙값은 해당 tier×method의 모든 k·seed 행을 합쳐 낸 값이다.",
    }


def _digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", default="artifacts/walk_graph_v1.pkl")
    parser.add_argument("--data-version", default="v2-2026-08-25")
    parser.add_argument("--scenarios", default=str(DATASETS_DIR / "shortest_path.json"))
    parser.add_argument("--k", type=int, nargs="+", default=[4, 8, 16])
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument(
        "--methods",
        nargs="+",
        choices=ALL_METHODS,
        default=None,
        help="측정할 방식. 생략하면 6개 전부를 잰다.",
    )
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args()

    if args.repeats < 1:
        parser.error("repeats는 1 이상이어야 합니다.")
    if any(k < 1 for k in args.k):
        parser.error("k는 전부 1 이상이어야 합니다.")

    out_dir = Path(
        args.out_dir
        or RESULTS_DIR / "shortest_path" / datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(args.scenarios, encoding="utf-8") as handle:
        dataset = json.load(handle)
    scenarios = dataset["scenarios"]

    graph = GraphArtifactRepository.load(
        args.artifact, expected_data_version=args.data_version
    )
    weight_fn = distance_weight
    pairs = [(sc["start"]["node_id"], sc["end"]["node_id"]) for sc in scenarios]
    baseline = {sc["id"]: sc["dijkstra_m"] for sc in scenarios}

    configs = iter_configs(args.k, args.seeds, args.methods)
    if not configs:
        parser.error("고른 --methods 조합에서 잴 것이 없습니다.")
    print(
        f"그래프 노드 {graph.number_of_nodes()}개 / 시나리오 {len(scenarios)}개 / "
        f"조합 {len(configs)}개 / 반복 {args.repeats}회 → 결과 {out_dir}"
    )

    rows: list[dict] = []
    config_stats: list[dict] = []
    run_start = perf_counter()

    for i, config in enumerate(configs, 1):
        label = f"{config['method']}(k={config['k']}, seed={config['seed']})"
        t0 = perf_counter()
        prepared = prepare_config(config, graph, weight_fn, pairs)
        prep_s = perf_counter() - t0
        print(
            f"[{i}/{len(configs)}] {label} 전처리 {prep_s:.1f}s "
            f"(선정 {prepared['select_s'] or 0:.1f}s / 거리표 {prepared['table_s'] or 0:.1f}s, "
            f"랜드마크 {prepared['k_actual']}, admissibility 위반 alt={prepared['alt_violations']} "
            f"hav={prepared['haversine_violations']})",
            flush=True,
        )

        for scenario in scenarios:
            rows.append(
                run_scenario(graph, scenario, config, prepared, weight_fn, args.repeats, baseline)
            )

        config_stats.append(
            {
                "method": config["method"],
                "k_requested": config["k"],
                "seed": config["seed"],
                "k_actual": prepared["k_actual"],
                "landmarks": prepared["landmarks"],
                "select_s": prepared["select_s"],
                "table_s": prepared["table_s"],
                "table_entries": prepared["table_entries"],
                "table_bytes": prepared["table_bytes"],
                "alt_violations": prepared["alt_violations"],
                "haversine_violations": prepared["haversine_violations"],
                "checked_pairs": prepared["checked_pairs"],
            }
        )
        # 거리표는 k=16에서 수백 MB가 될 수 있어 조합이 끝나면 바로 버린다.
        prepared["table"] = None
        prepared["heuristic"] = None
        print(
            f"        누적 {perf_counter() - run_start:.0f}s, 행 {len(rows)}개",
            flush=True,
        )

    csv_path = out_dir / "results.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    summary = build_summary(rows, config_stats)
    with (out_dir / "summary.json").open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)

    save_run_metadata(
        csv_path,
        runner="benchmarks.runner.alt_shortest_path",
        artifact=args.artifact,
        artifact_sha256=_digest(Path(args.artifact)),
        data_version=args.data_version,
        scenarios_file=args.scenarios,
        scenarios_meta=dataset.get("meta"),
        ks=args.k,
        seeds=args.seeds,
        repeats=args.repeats,
        methods_requested=args.methods or list(ALL_METHODS),
        methods=[c["method"] for c in configs],
        weight="benchmarks.runner.test_oneway_shortest_path.distance_weight",
        elapsed_s=perf_counter() - run_start,
        landmark_code_sha256={p: _digest(_ROOT / p) for p in _TRACKED_SOURCES},
    )

    mismatches = [r for r in rows if not r["cost_match"]]
    invalid = [r for r in rows if not r["path_valid"]]
    violations = [c for c in config_stats if c["alt_violations"] or c["haversine_violations"]]
    print(f"\n결과 {len(rows)}행 저장: {csv_path}")
    print(f"cost 불일치 {len(mismatches)}건 / 경로 무효 {len(invalid)}건 / "
          f"admissibility 위반 조합 {len(violations)}개")
    for row in mismatches[:10]:
        print(f"  [cost] {row['scenario_id']} {row['method']} k={row['k_requested']} "
              f"seed={row['seed']} path_m={row['path_m']} dijkstra_m={row['dijkstra_m']}")

    print(f"\n{'tier':<12}{'method':<11}{'popped(중앙)':>14}{'search_s(중앙)':>16}{'cost_match':>12}")
    for entry in summary["by_tier_method"]:
        print(
            f"{entry['tier']:<12}{entry['method']:<11}{entry['popped_median']:>14,.0f}"
            f"{entry['search_median_s_median']:>16.4f}{entry['cost_match_ratio']:>12.2f}"
        )


if __name__ == "__main__":
    main()
