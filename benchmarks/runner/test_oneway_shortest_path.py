"""
benchmarks/runner/test_oneway_shortest_path.py

Dijkstra vs Bidirectional Dijkstra vs A* 속도 비교 테스트 (거리 전용 weight 기준, 2026-08-23)
- production 엔진(dijkstra.py/oneway_astar.py/oneway_bi_astar.py)과 동일하게
  weight=length(m), A* heuristic=Haversine 직선거리(m)를 쓴다 — profile 가중치 블렌딩은 없다.
- benchmarks/config.py 의 상수를 그대로 사용
- oneway 테스트 케이스만 대상으로 함 (편도 최단경로 문제)
- 실행: python -m benchmarks.runner.test_oneway_shortest_path
"""

import time
import statistics
import json
import math
import gc 

import pandas as pd
import networkx as nx

from benchmarks.config import (
    ROUTE_NODES_PARQUET,
    ROUTE_EDGES_PARQUET,
    ROUTE_ENGINE_DATASET,
    RESULTS_DIR,
    LATENCY_REPEAT,
)
from src.route_engine.engines.path_utils import PathUtils

# ────────────────────────────────────────────────
# 1. weight/heuristic — production 엔진(scoring_engine.compute_distance_only_lookup,
#    oneway_astar.OnewayAstarEngine._heuristic)과 동일하게 거리(length, m)만 쓴다.
#    profile 가중치 블렌딩은 더 이상 반영하지 않는다.
# ────────────────────────────────────────────────
def distance_weight(u, v, edge_data: dict) -> float:
    """scoring_engine.py compute_distance_only_lookup과 동일한 공식(m 단위)."""
    return max(1.0, float(edge_data.get("length", 1.0) or 1.0))


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    """A* heuristic 및 노드 매칭에 쓰는 직선거리(m). PathUtils._haversine_m과 동일 공식."""
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


# ────────────────────────────────────────────────
# 2. 그래프 로드 (parquet fixture 사용)
# ────────────────────────────────────────────────
def load_graph() -> nx.Graph:
    nodes_df = pd.read_parquet(ROUTE_NODES_PARQUET)
    edges_df = pd.read_parquet(ROUTE_EDGES_PARQUET)

    G = nx.Graph()
    for row in nodes_df.itertuples():
        G.add_node(row.node_id, lat=row.lat, lon=row.lon)
    for row in edges_df.itertuples():
        G.add_edge(row.u, row.v, length=row.length)
    return G


def astar_heuristic_fn(G: nx.Graph):
    """admissible heuristic: 직선거리(m). weight가 length(m) 그대로이므로 별도 보정이 필요 없다."""
    def h(u, v):
        lat1, lon1 = G.nodes[u]["lat"], G.nodes[u]["lon"]
        lat2, lon2 = G.nodes[v]["lat"], G.nodes[v]["lon"]
        return haversine_m(lat1, lon1, lat2, lon2)
    return h


def path_cost(G: nx.Graph, path: list, weight_fn) -> float:
    """경로 노드 리스트로 총 비용 계산"""
    return sum(
        weight_fn(path[i], path[i + 1], G[path[i]][path[i + 1]])
        for i in range(len(path) - 1)
    )


# ────────────────────────────────────────────────
# 3. 좌표 → 가장 가까운 그래프 노드 찾기
#    PathUtils.find_nearest_node 재사용: 최대 연결 컴포넌트 필터 포함(실제 엔진과 동일)
# ────────────────────────────────────────────────
def find_nearest_node(utils: PathUtils, lat: float, lon: float) -> int | None:
    return utils.find_nearest_node(lat, lon)


# ────────────────────────────────────────────────
# 4. 반복 측정 유틸 (워밍업 제외 + 평균/표준편차/CV)
# ────────────────────────────────────────────────
def time_repeated(fn, repeat: int = LATENCY_REPEAT, warmup: int = 1):  
    times = []
    result = None
    gc.disable()  # ← 추가: 타이밍 재는 동안 GC 끄기
    try:
        for i in range(repeat + warmup):
            start = time.perf_counter()
            result = fn()
            elapsed = time.perf_counter() - start
            if i >= warmup:  # 워밍업 1회 제외
                times.append(elapsed * 1000)  # ms 단위
    finally:
        gc.enable()  # ← 무조건 다시 켜기
    mean = statistics.mean(times)
    std = statistics.pstdev(times) if len(times) > 1 else 0.0
    cv = (std / mean * 100) if mean > 0 else 0.0
    return result, {"mean_ms": mean, "std_ms": std, "cv_pct": cv}


# ────────────────────────────────────────────────
# 5. 메인 테스트 루프
# ────────────────────────────────────────────────
def main():
    print("그래프 로딩 중...")
    G = load_graph()
    print(f"노드 {G.number_of_nodes()}개, 엣지 {G.number_of_edges()}개 로드 완료")

    utils = PathUtils(G)

    with open(ROUTE_ENGINE_DATASET, encoding="utf-8") as f:
        dataset = json.load(f)

    scenarios = dataset["scenarios"]
    oneway_cases = [c for c in scenarios if c["mode"] == "oneway"]
    print(f"oneway 테스트 케이스 {len(oneway_cases)}개 대상으로 진행")

    # weight/heuristic이 더 이상 profile에 의존하지 않으므로 루프 밖에서 한 번만 계산한다.
    weight_fn = distance_weight
    heuristic = astar_heuristic_fn(G)

    cost_mismatches = []
    rows = []
    for case in oneway_cases:
        profile = case["profile"]  # 결과 기록용으로만 남김 — weight/heuristic에는 더 이상 영향 없음

        start_node = find_nearest_node(utils, case["start_lat"], case["start_lon"])
        end_node   = find_nearest_node(utils, case["end_lat"],   case["end_lon"])

        # ① 현재 방식: 단방향 Dijkstra
        dijkstra_path, dijkstra_stat = time_repeated(
            lambda: nx.dijkstra_path(G, start_node, end_node, weight=weight_fn),
            repeat=15
        )

        # ② Bidirectional Dijkstra  — 반환값: (cost, path)
        bidir_result, bidir_stat = time_repeated(
            lambda: nx.bidirectional_dijkstra(G, start_node, end_node, weight=weight_fn),
            repeat=15
        )

        # ③ A*
        astar_path, astar_stat = time_repeated(
            lambda: nx.astar_path(G, start_node, end_node, heuristic=heuristic, weight=weight_fn),
            repeat=15
        )

        # ── cost 검증 ──────────────────────────────────────────────
        dijkstra_cost = path_cost(G, dijkstra_path, weight_fn)
        bidir_cost    = bidir_result[0]
        astar_cost    = path_cost(G, astar_path, weight_fn)

        tol = max(1e-4, dijkstra_cost * 1e-6)  # 상대 허용 오차
        cost_ok = (
            abs(dijkstra_cost - bidir_cost) <= tol
            and abs(dijkstra_cost - astar_cost) <= tol
        )
        if not cost_ok:
            cost_mismatches.append({
                "case_id": case["id"],
                "dijkstra": dijkstra_cost,
                "bidir":    bidir_cost,
                "astar":    astar_cost,
            })

        rows.append({
            "case_id": case["id"],
            "profile": profile,
            "dijkstra_mean_ms": round(dijkstra_stat["mean_ms"], 2),
            "dijkstra_cv_pct": round(dijkstra_stat["cv_pct"], 1),
            "bidirectional_mean_ms": round(bidir_stat["mean_ms"], 2),
            "bidirectional_cv_pct": round(bidir_stat["cv_pct"], 1),
            "astar_mean_ms": round(astar_stat["mean_ms"], 2),
            "astar_cv_pct": round(astar_stat["cv_pct"], 1),
            "dijkstra_cost": round(dijkstra_cost, 4),
            "bidir_cost":    round(bidir_cost, 4),
            "astar_cost":    round(astar_cost, 4),
            "cost_match":    cost_ok,
        })
        cost_tag = "✓" if cost_ok else "✗ COST MISMATCH"
        print(
            f"[{case['id']}] Dijkstra {dijkstra_stat['mean_ms']:.1f}ms "
            f"(CV {dijkstra_stat['cv_pct']:.1f}%) | "
            f"Bidir {bidir_stat['mean_ms']:.1f}ms (CV {bidir_stat['cv_pct']:.1f}%) | "
            f"A* {astar_stat['mean_ms']:.1f}ms (CV {astar_stat['cv_pct']:.1f}%) | "
            f"cost {cost_tag}"
        )

    result_df = pd.DataFrame(rows)
    out_dir = RESULTS_DIR / "oneway_shortest_path"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "bidir_astar_latency.csv"
    result_df.to_csv(out_path, index=False)
    print(f"\n결과 저장 완료: {out_path}")

    # cost 불일치 경고 (이론상 세 알고리즘의 최적 비용은 동일해야 함)
    if cost_mismatches:
        print(f"\n[COST MISMATCH] {len(cost_mismatches)}건 — 알고리즘 간 최적 비용 불일치:")
        for m in cost_mismatches:
            print(
                f"  case={m['case_id']}  dijkstra={m['dijkstra']:.6f}  "
                f"bidir={m['bidir']:.6f}  astar={m['astar']:.6f}"
            )
    else:
        print("\n[cost OK] 모든 케이스에서 세 알고리즘의 최적 비용 일치")

    # CV 5% 넘는 케이스 경고 표시 (방법론 문서 판단 기준)
    unstable = result_df[
        (result_df["dijkstra_cv_pct"] > 5)
        | (result_df["bidirectional_cv_pct"] > 5)
        | (result_df["astar_cv_pct"] > 5)
    ]
    if not unstable.empty:
        print(f"\n[CV >5%] {len(unstable)}건 — 재측정 또는 원인 확인 필요:")
        print(unstable[["case_id", "dijkstra_cv_pct", "bidirectional_cv_pct", "astar_cv_pct"]])


if __name__ == "__main__":
    main()