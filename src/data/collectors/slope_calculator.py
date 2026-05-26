"""
slope_calculator.py
────────────────────────────────────────────────────────
OSMnx의 add_node_elevations_raster() 방식을 참고하여
walk_nodes에 고도값을 붙이고, walk_edges의 slope_score를 계산.

OSMnx 방식의 핵심:
  1. 모든 노드 좌표를 한 번에 rasterio.sample()로 배치 샘플링
  2. DEM CRS 자동 감지 → pyproj로 좌표 변환
  3. 노드별 고도값으로 엣지 경사율 계산

실행:
  python -m src.data.collectors.slope_calculator
"""

import os
import numpy as np
from sqlalchemy import text
from src.database.postgresql import engine

# ─────────────────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────────────────

DEM_PATH = os.getenv("DEM_PATH", "src/data/raw/dem/한반도90m_GRS80.img")
MAX_SLOPE_PCT = 10.0  # 이 이상이면 slope_score = 0.0
BATCH_SIZE = 5000


# ─────────────────────────────────────────────────────────
# Step 1. 노드 전체를 rasterio.sample()로 배치 샘플링
# ─────────────────────────────────────────────────────────


def get_node_elevations(dem_path: str) -> dict:
    """
    walk_nodes 전체 좌표를 rasterio.sample()로 한 번에 샘플링.
    OSMnx add_node_elevations_raster()와 동일한 방식.

    Returns:
        {node_id: elevation_m or None}
    """
    import rasterio
    from pyproj import Transformer

    print("\n[1/4] 노드 좌표 조회 중...")
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT node_id,
                   ST_X(geom) AS lon,
                   ST_Y(geom) AS lat
            FROM walk_nodes
            ORDER BY node_id
        """)).fetchall()

    if not rows:
        raise RuntimeError(
            "walk_nodes가 비어있습니다. load_network_safe를 먼저 실행하세요."
        )

    print(f"  ✅ {len(rows):,}개 노드 조회 완료")

    print("\n[2/4] DEM 고도 샘플링 중...")
    with rasterio.open(dem_path) as dataset:
        print(f"  DEM CRS    : {dataset.crs}")
        print(f"  DEM 해상도 : {dataset.width}×{dataset.height} px")
        print(f"  DEM Bounds : {dataset.bounds}")

        # WGS84 → DEM 좌표계 자동 변환 (OSMnx와 동일)
        transformer = Transformer.from_crs("EPSG:4326", dataset.crs, always_xy=True)

        node_ids = [r.node_id for r in rows]
        coords_dem = [transformer.transform(r.lon, r.lat) for r in rows]

        # 변환 검증
        x0, y0 = coords_dem[0]
        b = dataset.bounds
        in_bounds = b.left < x0 < b.right and b.bottom < y0 < b.top
        print(f"\n  [변환 검증] 첫 노드 WGS84({rows[0].lon:.4f}, {rows[0].lat:.4f})")
        print(f"             → DEM좌표({x0:.1f}, {y0:.1f})")
        print(f"             DEM 범위 내: {'✅ YES' if in_bounds else '❌ NO'}")

        if not in_bounds:
            raise RuntimeError("좌표 변환 실패. DEM 범위를 벗어났습니다.")

        # ★ OSMnx 핵심: rasterio.sample()로 전체 노드 한 번에 배치 샘플링
        nodata = dataset.nodata
        sampled = list(dataset.sample(coords_dem, indexes=1))

    elevations = {}
    for node_id, elev_arr in zip(node_ids, sampled):
        val = float(elev_arr)
        if (nodata is not None and val == nodata) or np.isnan(val):
            elevations[node_id] = None
        else:
            elevations[node_id] = val

    valid = sum(1 for v in elevations.values() if v is not None)
    print(f"  ✅ 샘플링 완료: 유효 {valid:,} / 전체 {len(elevations):,}개")
    return elevations


# ─────────────────────────────────────────────────────────
# Step 2. 엣지별 slope_score 계산
# ─────────────────────────────────────────────────────────


def slope_pct_to_score(slope_pct: float) -> float:
    return max(0.0, round(1.0 - slope_pct / MAX_SLOPE_PCT, 6))


def calculate_edge_slopes(elevations: dict) -> list:
    """
    노드 고도값을 이용해 엣지별 slope_score 계산.
    """
    print("\n[3/4] 엣지 경사 점수 계산 중...")

    with engine.connect() as conn:
        edges = conn.execute(text("""
            SELECT link_id, start_node, end_node, length_m
            FROM walk_edges
            ORDER BY link_id
        """)).fetchall()

    if not edges:
        raise RuntimeError("walk_edges가 비어있습니다.")

    updates = []
    skipped = 0

    for edge in edges:
        elev_start = elevations.get(edge.start_node)
        elev_end = elevations.get(edge.end_node)

        if elev_start is None or elev_end is None:
            score = 0.5  # 고도 없는 노드 → 중립값
            skipped += 1
        else:
            elev_diff = abs(elev_end - elev_start)
            length_m = max(edge.length_m or 1.0, 1.0)
            slope_pct = (elev_diff / length_m) * 100.0
            score = slope_pct_to_score(slope_pct)

        updates.append({"link_id": edge.link_id, "slope_score": score})

    print(f"  ✅ 계산 완료 (고도 없는 엣지 → 0.5 처리: {skipped:,}개)")
    return updates


# ─────────────────────────────────────────────────────────
# Step 3. DB 업데이트
# ─────────────────────────────────────────────────────────


def update_db(updates: list):
    print(f"\n[4/4] DB 업데이트 중... ({len(updates):,}개, 배치 {BATCH_SIZE:,})")
    total = 0
    with engine.begin() as conn:
        for i in range(0, len(updates), BATCH_SIZE):
            batch = updates[i : i + BATCH_SIZE]
            conn.execute(
                text(
                    "UPDATE walk_edges SET slope_score = :slope_score WHERE link_id = :link_id"
                ),
                batch,
            )
            total += len(batch)
            print(f"  → {total:,} / {len(updates):,} 완료")


# ─────────────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────────────


def calculate_slope_scores():
    print("=" * 60)
    print("📐 slope_calculator (OSMnx 방식) 시작")
    print(f"   DEM 파일      : {DEM_PATH}")
    print(f"   최대 경사 기준 : {MAX_SLOPE_PCT}%")
    print("=" * 60)

    elevations = get_node_elevations(DEM_PATH)
    updates = calculate_edge_slopes(elevations)
    update_db(updates)

    scores = [u["slope_score"] for u in updates]
    real = [s for s in scores if s != 0.5]

    print("\n" + "=" * 60)
    print("🎉 slope_score 업데이트 완료!")
    print(f"   처리 엣지 수     : {len(updates):,}개")
    print(f"   실제 계산 엣지   : {len(real):,}개")
    print(f"   고도 없는 엣지   : {len(updates) - len(real):,}개 (0.5 처리)")
    if real:
        print(f"   평균 slope_score : {sum(real) / len(real):.4f}")
        print(f"   최솟값 / 최댓값  : {min(real):.4f} / {max(real):.4f}")
    print("=" * 60)


if __name__ == "__main__":
    calculate_slope_scores()
