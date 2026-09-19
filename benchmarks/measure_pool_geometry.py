"""
benchmarks/measure_pool_geometry.py

이슈 "구축 단계 원형성 지향 항 추가" 1단계 사전 계측 중, 추가 A* 호출이 0회인 두 항목.

(A) 후보 풀의 우회계수 이방성
    우회계수 = dist_from_p1(A* 도로 거리) / haversine(p1, node)(직선거리).
    두 값 모두 풀 생성 시점에 이미 존재하므로 새 경로 탐색이 필요 없다. 방위각 섹터별
    분포를 내서 "평균 계수 하나로 R=L/(2π)를 보정할 수 있는가"를 판정한다 — 섹터 간
    중앙값이 크게 벌어지면 단일 계수 보정은 성립하지 않는다.

(B) Beam depth 1 생존자의 방위각 분포
    beam_search()의 첫 확장은 cost(start, c)와 cost(c, start)만 쓰는데, 어댑터
    (waypoint_pool_beam_adapter.py::waypoint_pool_cost_function)에서 두 호출 모두
    dist_from_p1 분기를 타므로 pairwise SSSP가 한 번도 돌지 않는다. 그래서 depth 1
    랭킹은 풀만 있으면 그대로 재현된다 — 전체 탐색을 돌리지 않고 같은 랭킹식을 직접
    계산한다. 랭킹식은 waypoint_beam.py::expand()의 첫 단계와 같다:
        remaining_legs = N, balanced_m = target_m*N/(N+1)
        rank_m = d + max(d, balanced_m)   (N=1이면 rank_m = 2d)
        key    = (|rank_m - target_m|, node_id)
    첫 경유지에는 방향 페널티도 최소거리 필터도 걸리지 않으므로(둘 다 a==start_node에서
    빠진다) 이 식이 depth 1 생존자를 전부 결정한다.

실행:
    poetry run python -m benchmarks.measure_pool_geometry

주의: 벤치 계열은 poetry 환경(3.12)에서 실행한다. 셸 기본 python(3.11)과 거리 계산
끝자리가 달라진다.
"""

import csv
import math
import time
from heapq import nsmallest

from benchmarks.benchmark import _load_default_graph
from benchmarks.config import RESULTS_DIR
from src.route_engine.engines.grasp_waypoint_common import _bearing_rad
from src.route_engine.engines.waypoint_pool import WaypointPoolGenerator
from src.route_engine.scoring.scoring_engine import precompute_scoring_features

_EARTH_RADIUS_M = 6371008.8  # benchmarks/results.py와 같은 WGS84 평균 반지름

# run_geometry_validation.py와 동일한 5개 출발지 — 다른 1단계 산출물과 조건을 맞춘다.
# 주의: 이 5개의 선정 기준은 기록이 없다. 결과는 "이 5개 출발지에서 관측된 값"으로만 읽는다.
START_NODE_COORDS = {
    1:      (37.564088, 126.902572),
    41417:  (37.575209, 126.928363),
    111383: (37.518967, 126.889364),
    175895: (37.596433, 127.094927),
    179044: (37.528862, 127.004334),
}
TARGET_KMS = [3.0, 5.0]
NUM_WAYPOINTS = [2, 4]          # 2=현재 기본값, 4=이슈가 실제로 겨냥하는 구간
BEAM_WIDTH = 8                  # GraspConfig.rcl_size 기본값과 맞춘 공정 비교 기본값
PAIRWISE_CACHE_ROWS = 256       # GraspConfig.pairwise_cache_rows 기본값과 동일
SECTOR_DEG = 30                 # 360도를 12섹터로


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return math.degrees(_bearing_rad(lat1, lon1, lat2, lon2)) % 360.0


def _quantile(values, q: float):
    """선형 보간 분위수. statistics.quantiles는 표본이 2개 미만이면 예외라 직접 계산한다."""
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    pos = q * (len(s) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return s[lo]
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def circular_span_deg(bearings) -> float:
    """방위각 목록을 모두 담는 최소 호의 크기(도). 가장 큰 빈 구간을 360에서 뺀다."""
    if len(bearings) < 2:
        return 0.0
    s = sorted(b % 360.0 for b in bearings)
    gaps = [s[i + 1] - s[i] for i in range(len(s) - 1)]
    gaps.append(s[0] + 360.0 - s[-1])  # 마지막에서 처음으로 돌아오는 구간
    return 360.0 - max(gaps)


def _pool_entries(pool_result, start_node: int):
    """어댑터가 beam에 넘기는 후보 집합과 정확히 같은 (node_id, dist_from_p1) 목록."""
    return [
        (nid, pool_result.dist_from_p1[nid])
        for nid in pool_result.pool_nodes
        if nid != start_node and nid in pool_result.dist_from_p1
    ]


def _detour_rows(G, start_node: int, target_km: float, pool_result) -> list:
    """(A) 방위각 섹터별 우회계수 분포."""
    p1 = G.nodes[start_node]
    by_sector: dict = {}
    for node_id, road_m in _pool_entries(pool_result, start_node):
        data = G.nodes[node_id]
        if "lat" not in data or "lon" not in data:
            continue
        straight_m = _haversine_m(p1["lat"], p1["lon"], data["lat"], data["lon"])
        if straight_m <= 0:
            continue  # p1과 좌표가 같은 노드 — 우회계수가 정의되지 않는다
        bearing = _bearing_deg(p1["lat"], p1["lon"], data["lat"], data["lon"])
        sector = int(bearing // SECTOR_DEG) * SECTOR_DEG
        by_sector.setdefault(sector, []).append(road_m / straight_m)

    rows = []
    for sector in range(0, 360, SECTOR_DEG):
        ratios = by_sector.get(sector, [])
        rows.append({
            "start_node": start_node,
            "target_km": target_km,
            "sector_deg": sector,
            "n": len(ratios),
            "detour_p10": _quantile(ratios, 0.10),
            "detour_median": _quantile(ratios, 0.50),
            "detour_p90": _quantile(ratios, 0.90),
        })
    return rows


def _depth1_rows(G, start_node: int, target_km: float, pool_result, num_waypoints: int) -> list:
    """(B) Beam depth 1 생존 상위 BEAM_WIDTH개와 그 방위각."""
    target_m = target_km * 1000
    n = num_waypoints
    balanced_m = target_m * n / (n + 1)

    def rank_m(d: float) -> float:
        # waypoint_beam.py::expand()의 첫 단계와 같은 식(remaining_legs == N).
        return (d + max(d, balanced_m)) if n > 1 else 2 * d

    def key(item):
        node_id, d = item
        return (abs(rank_m(d) - target_m), node_id)  # 동점은 ID 순 — beam과 같은 규칙

    top = nsmallest(BEAM_WIDTH, _pool_entries(pool_result, start_node), key=key)
    p1 = G.nodes[start_node]

    rows, bearings = [], []
    for rank, (node_id, d) in enumerate(top, 1):
        data = G.nodes[node_id]
        bearing = _bearing_deg(p1["lat"], p1["lon"], data["lat"], data["lon"])
        bearings.append(bearing)
        rows.append({
            "start_node": start_node,
            "target_km": target_km,
            "num_waypoints": n,
            "rank": rank,
            "node_id": node_id,
            "bearing_deg": round(bearing, 2),
            "dist_from_p1_m": round(d, 2),
            "rank_error_m": round(abs(rank_m(d) - target_m), 2),
            "sectors_covered": None,  # 아래에서 생존자 전체 기준으로 채운다
            "span_deg": None,
        })

    # 생존자 전체를 본 뒤에야 정해지는 값이라, 모든 행에 같은 값을 덮어쓴다 —
    # 조인 없이 이 파일 하나만 읽어도 판정이 되게 한다.
    sectors = len({int(b // SECTOR_DEG) for b in bearings})
    span = round(circular_span_deg(bearings), 2)
    for row in rows:
        row["sectors_covered"], row["span_deg"] = sectors, span
    return rows


def _write(path, rows: list) -> None:
    if not rows:
        print(f"[건너뜀] 기록할 행이 없습니다: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"저장 완료: {path} ({len(rows)}행)")


def main() -> None:
    t0 = time.perf_counter()
    G = _load_default_graph()
    if G is None:
        raise SystemExit(
            "[오류] Graph artifact가 없습니다. artifacts/walk_graph_v1.pkl과 "
            "manifest·sha256 파일이 있는지 확인하세요."
        )
    precompute_scoring_features(G)
    print(f"그래프 로드 완료: {time.perf_counter() - t0:.1f}초", flush=True)

    detour_rows, depth1_rows = [], []
    for start_node in START_NODE_COORDS:
        for target_km in TARGET_KMS:
            data = G.nodes[start_node]
            pool_result = WaypointPoolGenerator(G).build_pool(
                data.get("lat", 0.0), data.get("lon", 0.0), target_km,
                pairwise_cache_rows=PAIRWISE_CACHE_ROWS,
            )
            if pool_result is None or not pool_result.pool_nodes:
                print(f"[건너뜀] start={start_node} target_km={target_km}: 후보 풀이 비었습니다", flush=True)
                continue
            detour_rows += _detour_rows(G, start_node, target_km, pool_result)
            for n in NUM_WAYPOINTS:
                depth1_rows += _depth1_rows(G, start_node, target_km, pool_result, n)
            print(
                f"start={start_node} target_km={target_km} pool={len(pool_result.pool_nodes)} 완료",
                flush=True,
            )

    _write(RESULTS_DIR / "pool_detour_by_bearing.csv", detour_rows)
    _write(RESULTS_DIR / "beam_depth1_bearings.csv", depth1_rows)
    print(f"\n전체 소요 시간: {time.perf_counter() - t0:.1f}초")


if __name__ == "__main__":
    main()
