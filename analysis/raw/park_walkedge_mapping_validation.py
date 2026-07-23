"""공원 Polygon과 도보 WalkEdge의 공간 매핑 방식을 로컬에서 비교합니다."""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely


LOGGER = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
WALK_NETWORK_PATH = ROOT / "src/data/raw/서울시 자치구별 도보 네트워크 공간정보.csv"
PARK_SHP_PATH = ROOT / "src/data/raw/서울시 생활권계획 시설(공원) 공간정보.shp"
OUTPUT_DIR = ROOT / "analysis/tables/raw"
SUMMARY_PATH = OUTPUT_DIR / "park_walkedge_mapping_summary.csv"
DISAGREEMENT_PATH = OUTPUT_DIR / "park_walkedge_mapping_disagreements.csv"
PROXIMITY_PATH = OUTPUT_DIR / "park_walkedge_raw_flag_proximity.csv"

PROJECTED_CRS = "EPSG:5179"
RATIO_THRESHOLDS = (0.1, 0.5)


def read_csv_with_fallback(path: Path, **kwargs) -> pd.DataFrame:
    for encoding in ("cp949", "utf-8-sig", "utf-8"):
        try:
            return pd.read_csv(path, encoding=encoding, **kwargs)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("unknown", b"", 0, 1, f"지원하지 않는 인코딩: {path}")


def load_walk_edges() -> gpd.GeoDataFrame:
    required = [
        "노드링크 유형",
        "링크 ID",
        "링크 WKT",
        "링크 길이",
        "공원,녹지",
        "시군구명",
        "읍면동명",
    ]
    raw = read_csv_with_fallback(WALK_NETWORK_PATH, usecols=required)
    links = raw.loc[raw["노드링크 유형"].eq("LINK")].copy()
    links["link_id"] = pd.to_numeric(links["링크 ID"], errors="raise").astype("int64")
    links["source_length_m"] = pd.to_numeric(links["링크 길이"], errors="coerce")
    links["raw_is_park_green"] = (
        pd.to_numeric(links["공원,녹지"], errors="raise").astype("int8").eq(1)
    )

    geometry = gpd.GeoSeries.from_wkt(links["링크 WKT"], crs="EPSG:4326")
    edges = gpd.GeoDataFrame(
        links[
            [
                "link_id",
                "source_length_m",
                "raw_is_park_green",
                "시군구명",
                "읍면동명",
            ]
        ].rename(columns={"시군구명": "district", "읍면동명": "neighborhood"}),
        geometry=geometry,
        crs="EPSG:4326",
    )
    if edges.geometry.isna().any() or edges.geometry.is_empty.any():
        raise ValueError("도보 LINK에 비어 있는 geometry가 있습니다.")
    return edges.to_crs(PROJECTED_CRS).reset_index(drop=True)


def load_park_polygons() -> gpd.GeoDataFrame:
    parks = gpd.read_file(PARK_SHP_PATH)
    if parks.crs is None:
        raise ValueError("공원 Shapefile의 좌표계가 없습니다.")

    required = {"ID", "LABEL"}
    missing = required - set(parks.columns)
    if missing:
        raise ValueError(f"공원 Shapefile 필수 컬럼 누락: {sorted(missing)}")

    parks = parks[parks.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    parks.geometry = parks.geometry.make_valid()
    parks = parks[
        parks.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
        & ~parks.geometry.is_empty
    ].copy()
    if parks.empty:
        raise ValueError("유효한 공원 Polygon이 없습니다.")
    return (
        parks[["ID", "LABEL", "geometry"]]
        .to_crs(PROJECTED_CRS)
        .reset_index(drop=True)
    )


def build_park_parts(parks: gpd.GeoDataFrame) -> np.ndarray:
    """겹치는 공원 Polygon을 합쳐 중복 길이 계산을 방지한다."""
    park_union = shapely.union_all(parks.geometry.array)
    return np.asarray(shapely.get_parts(park_union), dtype=object)


def find_intersection_pairs(
    edges: gpd.GeoDataFrame,
    park_parts: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """공간 인덱스로 실제 교차하는 Edge·공원 구성요소 쌍만 찾는다."""
    tree = shapely.STRtree(park_parts)
    edge_positions, park_positions = tree.query(
        edges.geometry.array,
        predicate="intersects",
    )
    return edge_positions, park_positions


def flag_intersections(
    edges: gpd.GeoDataFrame,
    edge_positions: np.ndarray,
) -> pd.Series:
    flags = np.zeros(len(edges), dtype=bool)
    flags[np.unique(edge_positions)] = True
    return pd.Series(flags, index=edges.index)


def flag_midpoints_within(
    edges: gpd.GeoDataFrame,
    park_parts: np.ndarray,
) -> pd.Series:
    midpoints = shapely.line_interpolate_point(
        edges.geometry.array,
        0.5,
        normalized=True,
    )
    tree = shapely.STRtree(park_parts)
    midpoint_positions, _ = tree.query(midpoints, predicate="within")
    flags = np.zeros(len(edges), dtype=bool)
    flags[np.unique(midpoint_positions)] = True
    return pd.Series(flags, index=edges.index)


def calculate_overlap_ratio(
    edges: gpd.GeoDataFrame,
    park_parts: np.ndarray,
    edge_positions: np.ndarray,
    park_positions: np.ndarray,
    chunk_size: int = 20_000,
) -> pd.Series:
    overlap_lengths = np.zeros(len(edges), dtype=float)

    for start in range(0, len(edge_positions), chunk_size):
        end = min(start + chunk_size, len(edge_positions))
        edge_chunk = edge_positions[start:end]
        park_chunk = park_positions[start:end]
        intersections = shapely.intersection(
            edges.geometry.array.take(edge_chunk),
            park_parts.take(park_chunk),
        )
        np.add.at(overlap_lengths, edge_chunk, shapely.length(intersections))
        LOGGER.info(
            "공원 내부 길이 계산: %d/%d",
            end,
            len(edge_positions),
        )

    edge_lengths = shapely.length(edges.geometry.array)
    ratios = np.divide(
        overlap_lengths,
        edge_lengths,
        out=np.zeros_like(overlap_lengths),
        where=edge_lengths > 0,
    )
    return pd.Series(
        np.clip(ratios, 0.0, 1.0),
        index=edges.index,
        dtype="float64",
    )


def comparison_row(
    method: str,
    selected: pd.Series,
    raw_flag: pd.Series,
) -> dict[str, int | float | str]:
    selected = selected.astype(bool)
    raw_flag = raw_flag.astype(bool)
    both = selected & raw_flag
    selected_count = int(selected.sum())
    raw_count = int(raw_flag.sum())
    both_count = int(both.sum())
    precision = both_count / selected_count if selected_count else 0.0
    recall = both_count / raw_count if raw_count else 0.0
    union_count = int((selected | raw_flag).sum())
    jaccard = both_count / union_count if union_count else 0.0
    return {
        "method": method,
        "selected_edges": selected_count,
        "selected_ratio": selected_count / len(selected),
        "raw_park_green_edges": raw_count,
        "both_edges": both_count,
        "method_only_edges": int((selected & ~raw_flag).sum()),
        "raw_only_edges": int((~selected & raw_flag).sum()),
        "precision_vs_raw": precision,
        "recall_vs_raw": recall,
        "jaccard_vs_raw": jaccard,
    }


def summarize_raw_flag_proximity(
    edges: gpd.GeoDataFrame,
    park_parts: np.ndarray,
) -> pd.DataFrame:
    """원본 공원·녹지 LINK가 외부 공원 Polygon과 얼마나 가까운지 요약한다."""
    raw_flag_positions = np.flatnonzero(edges["raw_is_park_green"].to_numpy())
    tree = shapely.STRtree(park_parts)
    _, distances = tree.query_nearest(
        edges.geometry.array.take(raw_flag_positions),
        return_distance=True,
        all_matches=False,
    )
    rows = []
    for distance_m in (0, 5, 10, 30, 50, 100):
        matched = int(np.count_nonzero(distances <= distance_m))
        rows.append(
            {
                "distance_m": distance_m,
                "matched_raw_park_green_edges": matched,
                "total_raw_park_green_edges": len(raw_flag_positions),
                "matched_ratio": matched / len(raw_flag_positions),
            }
        )
    return pd.DataFrame(rows)


def run_analysis() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    LOGGER.info("도보 LINK 로드")
    edges = load_walk_edges()
    LOGGER.info("공원 Polygon 로드")
    parks = load_park_polygons()

    LOGGER.info("공원 합집합과 공간 인덱스 생성")
    park_parts = build_park_parts(parks)
    edge_positions, park_positions = find_intersection_pairs(edges, park_parts)

    LOGGER.info("ST_Intersects 방식 계산")
    edges["intersects_park"] = flag_intersections(edges, edge_positions)
    LOGGER.info("Edge 중점 포함 방식 계산")
    edges["midpoint_within_park"] = flag_midpoints_within(edges, park_parts)
    LOGGER.info("공원 내부 길이 비율 계산")
    edges["park_overlap_ratio"] = calculate_overlap_ratio(
        edges,
        park_parts,
        edge_positions,
        park_positions,
    )

    methods = {
        "intersects": edges["intersects_park"],
        "midpoint_within": edges["midpoint_within_park"],
        "overlap_ratio_ge_0.1": edges["park_overlap_ratio"].ge(RATIO_THRESHOLDS[0]),
        "overlap_ratio_ge_0.5": edges["park_overlap_ratio"].ge(RATIO_THRESHOLDS[1]),
    }
    summary = pd.DataFrame(
        [
            comparison_row(name, flag, edges["raw_is_park_green"])
            for name, flag in methods.items()
        ]
    )
    summary.insert(1, "total_edges", len(edges))
    summary["park_polygons"] = len(parks)
    proximity = summarize_raw_flag_proximity(edges, park_parts)

    disagreement_mask = (
        edges["intersects_park"].ne(edges["midpoint_within_park"])
        | edges["raw_is_park_green"].ne(edges["park_overlap_ratio"].ge(0.5))
    )
    disagreement = edges.loc[
        disagreement_mask,
        [
            "link_id",
            "district",
            "neighborhood",
            "source_length_m",
            "raw_is_park_green",
            "intersects_park",
            "midpoint_within_park",
            "park_overlap_ratio",
        ],
    ].copy()
    disagreement = disagreement.sort_values(
        ["raw_is_park_green", "park_overlap_ratio", "link_id"],
        ascending=[False, False, True],
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summary.to_csv(SUMMARY_PATH, index=False, encoding="utf-8-sig")
    disagreement.to_csv(DISAGREEMENT_PATH, index=False, encoding="utf-8-sig")
    proximity.to_csv(PROXIMITY_PATH, index=False, encoding="utf-8-sig")

    LOGGER.info("요약 저장: %s", SUMMARY_PATH)
    LOGGER.info("불일치 저장: %s (%d개)", DISAGREEMENT_PATH, len(disagreement))
    LOGGER.info("원본 플래그 근접도 저장: %s", PROXIMITY_PATH)
    return summary, disagreement, proximity


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(message)s",
    )
    result_summary, result_disagreement, result_proximity = run_analysis()
    print(result_summary.to_string(index=False))
    print("\n원본 공원·녹지 LINK와 공원 Polygon의 거리")
    print(result_proximity.to_string(index=False))
    print(f"\n불일치 Edge: {len(result_disagreement):,}개")
