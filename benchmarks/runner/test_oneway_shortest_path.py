"""
benchmarks/runner/test_oneway_shortest_path.py

현재 Dijkstra vs Bidirectional Dijkstra vs A* 속도 비교 테스트
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
# 1. 프로필별 가중치 — profiles.py PROFILES 딕셔너리 기준
#    "mode": "general" | "running" 은 scoring_engine의 분기 키
# ────────────────────────────────────────────────
PROFILE_WEIGHTS = {
    "default":  {"safety": 0.5, "nature": 0.5, "slope": 0.5, "landmark": 0.0, "child": 0.0, "running": 0.0, "mode": "general"},
    "nature":   {"safety": 0.5, "nature": 0.8, "slope": 0.5, "landmark": 0.0, "child": 0.0, "running": 0.0, "mode": "general"},
    "safe":     {"safety": 0.8, "nature": 0.5, "slope": 0.5, "landmark": 0.0, "child": 0.0, "running": 0.0, "mode": "general"},
    "flat":     {"safety": 0.5, "nature": 0.5, "slope": 0.8, "landmark": 0.0, "child": 0.0, "running": 0.0, "mode": "general"},
    "running":  {"safety": 0.5, "nature": 0.5, "slope": 0.5, "landmark": 0.0, "child": 0.0, "running": 0.8, "mode": "running"},
    "landmark": {"safety": 0.5, "nature": 0.5, "slope": 0.5, "landmark": 0.8, "child": 0.0, "running": 0.0, "mode": "general"},
    "child":    {"safety": 0.5, "nature": 0.5, "slope": 0.5, "landmark": 0.0, "child": 0.8, "running": 0.0, "mode": "general"},
}


def compute_custom_score(edge_data: dict, weights: dict) -> float:
    """
    scoring_engine.py calculate_custom_score 공식과 동일.

    general 모드:
        score = (length × (2 - slope)^slope_w) / (safety^a × nature^b × bonus)
        bonus = (1 + landmark × landmark_w) × (1 + child × child_w)  [weight > 0 시만]

    running 모드:
        score = (length × (1 + slope × slope_w)) /
                (safety × nature × (1 + running × running_w) × (1 + log1p(length/50)))
    """
    mode = weights.get("mode", "general")

    length = edge_data.get("length", 1.0) or 1.0
    # 실제 코드와 동일하게 [0, 1] 클램핑 + None/0 → 기본값 0.5
    safety = max(0.0, min(1.0, edge_data.get("safety_score",  0.5) or 0.5))
    nature = max(0.0, min(1.0, edge_data.get("nature_score",  0.5) or 0.5))
    slope  = max(0.0, min(1.0, edge_data.get("slope_score",   0.5) or 0.5))

    safety_w   = weights["safety"]
    nature_w   = weights["nature"]
    slope_w    = weights["slope"]
    landmark_w = weights.get("landmark", 0.0)
    child_w    = weights.get("child",    0.0)
    running_w  = weights.get("running",  0.0)

    if mode == "running":
        running      = max(0.0, min(1.0, edge_data.get("running_score", 0.0) or 0.0))
        running_bonus = 1.0 + running * running_w
        slope_factor  = 1.0 + slope * slope_w
        length_bonus  = 1.0 + math.log1p(length / 50.0)
        calculated    = (length * slope_factor) / (
            (safety + 1e-6) * (nature + 1e-6) * running_bonus * length_bonus
        )
    else:
        slope_penalty = (2.0 - slope) ** slope_w
        denominator   = (safety + 1e-6) ** safety_w * (nature + 1e-6) ** nature_w
        # landmark/child는 지수승이 아닌 가산 보너스 (scoring_engine.py 참조)
        if landmark_w > 0:
            denominator *= 1.0 + edge_data.get("landmark_score", 0.0) * landmark_w
        if child_w > 0:
            denominator *= 1.0 + edge_data.get("child_score", 0.0) * child_w
        calculated    = (length * slope_penalty) / denominator

    return max(1.0, calculated)


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    """A* heuristic 및 노드 매칭에 쓰는 직선거리(km)"""
    R = 6371.0
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
        G.add_edge(
            row.u, row.v,
            length=row.length,
            safety_score=getattr(row, "safety_score", 0.0),
            nature_score=getattr(row, "nature_score", 0.0),
            landmark_score=getattr(row, "landmark_score", 0.0),
            child_score=getattr(row, "child_score", 0.0),
        )
    return G


def build_weight_fn(profile: str):
    weights = PROFILE_WEIGHTS[profile]

    def weight_fn(u, v, edge_data):
        return compute_custom_score(edge_data, weights)

    return weight_fn


def compute_min_ratio(G: nx.Graph, profile: str) -> float:
    """프로필별 (비용/거리) 최솟값 → A* heuristic admissibility 보장"""
    weights = PROFILE_WEIGHTS[profile]
    return min(
        compute_custom_score(data, weights) / max(data.get("length", 1.0), 1e-6)
        for _, _, data in G.edges(data=True)
    )


def astar_heuristic_fn(G: nx.Graph, min_cost_per_km: float):
    """admissible heuristic: 직선거리(km) × 프로필별 최소 비용/km"""
    def h(u, v):
        lat1, lon1 = G.nodes[u]["lat"], G.nodes[u]["lon"]
        lat2, lon2 = G.nodes[v]["lat"], G.nodes[v]["lon"]
        return haversine_km(lat1, lon1, lat2, lon2) * min_cost_per_km
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

    cost_mismatches = []
    rows = []
    for case in oneway_cases:
        profile = case["profile"]
        if profile not in PROFILE_WEIGHTS:
            print(f"[{case['id']}] 프로필 '{profile}'은 이번 테스트 대상 아님 (skip)")
            continue

        weight_fn  = build_weight_fn(profile)
        # A* heuristic admissibility: 프로필별 min(비용/km) 사용
        min_ratio  = compute_min_ratio(G, profile)
        heuristic  = astar_heuristic_fn(G, min_ratio)

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