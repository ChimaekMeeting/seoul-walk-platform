"""
src/data/configured/configured_dataset.py
approved: true이고 dataset_type: configured인 데이터셋을 registry.yaml 설정만으로
읽고 정제해 표준 record로 만드는 loader.

이 모듈은 DB를 변경하지 않는다. CSVSource.TAGS나 collector를 수정하지 않고,
registry 설정(geometry/lat·lon 컬럼/서울 필터/score/profile/ai_expression)을
그대로 읽어 적재 전 단계의 표준 record를 만드는 준비 단계다. csv_raw 적재와
layer/score 반영은 다음 단계(ingest)에서 구현한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from src.data.intake.inspect_dataset import SEOUL_LAT_RANGE, SEOUL_LON_RANGE, read_dataset
from src.data.intake.registry import DEFAULT_REGISTRY_PATH, load_registry

DEFAULT_RAW_DIR = Path("src/data/raw")

SUPPORTED_SOURCE_TYPES = {"csv", "xlsx"}
SUPPORTED_GEOMETRY_TYPES = {"POINT", "LINESTRING"}

# score_column -> target_layer MVP 매핑. plan.py가 raw/layer 반영 계획을 세울 때 사용한다.
SCORE_COLUMN_TO_TARGET_LAYER = {
    "nature_score": "nature_layer",
    "safety_score": "safety_layer",
    "running_score": "running_layer",
    "child_score": "child_layer",
    "landmark_score": "landmark_layer",
}


def infer_target_layer(score_column: str | None) -> str:
    """registry entry의 score_column으로부터 target_layer를 추정합니다(MVP 규칙).

    매핑에 없는 score_column(또는 None)이면 "undecided"를 반환합니다.
    """
    if score_column is None:
        return "undecided"
    return SCORE_COLUMN_TO_TARGET_LAYER.get(score_column, "undecided")


class DatasetNotFoundError(ValueError):
    """registry.yaml에 dataset_key가 없을 때 발생합니다."""


class DatasetNotApprovedError(ValueError):
    """dataset의 approved가 true가 아닐 때 발생합니다."""


class UnsupportedDatasetTypeError(ValueError):
    """dataset_type이 configured가 아닐 때 발생합니다."""


class UnsupportedSourceTypeError(ValueError):
    """source_type이 csv/xlsx가 아닐 때 발생합니다."""


class UnsupportedGeometryError(ValueError):
    """geometry가 POINT/LINESTRING이 아닐 때 발생합니다."""


# ── registry 조회/검증 ────────────────────────────────────────────────────────


def get_approved_configured_dataset(registry: dict[str, Any], dataset_key: str) -> dict[str, Any]:
    """
    registry에서 approved: true, dataset_type: configured인 dataset entry를 가져옵니다.

    조건을 만족하지 않으면 각각의 에러를 발생시킵니다.
    """
    datasets = registry.get("datasets") or {}
    if dataset_key not in datasets:
        raise DatasetNotFoundError(f"dataset_key '{dataset_key}'를 registry.yaml에서 찾을 수 없습니다.")

    entry = datasets[dataset_key]

    if entry.get("approved") is not True:
        raise DatasetNotApprovedError(
            f"dataset_key '{dataset_key}'는 approved: true가 아닙니다. "
            "approve_dataset.py로 먼저 승인하세요."
        )

    if entry.get("dataset_type") != "configured":
        raise UnsupportedDatasetTypeError(
            f"dataset_key '{dataset_key}'는 dataset_type이 configured가 아닙니다 "
            f"(현재: {entry.get('dataset_type')!r}). adapter dataset은 전용 collector로 처리합니다."
        )

    if entry.get("source_type") not in SUPPORTED_SOURCE_TYPES:
        raise UnsupportedSourceTypeError(
            f"dataset_key '{dataset_key}'는 지원하지 않는 source_type입니다 "
            f"(현재: {entry.get('source_type')!r}, 지원: {sorted(SUPPORTED_SOURCE_TYPES)})."
        )

    return entry


# ── 서울 필터 ─────────────────────────────────────────────────────────────────


def apply_city_filter(df: pd.DataFrame, entry: dict[str, Any]) -> pd.DataFrame:
    """city_filter_col/city_filter_value가 설정되어 있으면 contains 필터를 적용합니다."""
    col = entry.get("city_filter_col")
    value = entry.get("city_filter_value")

    if not col or value in (None, ""):
        return df

    if col not in df.columns:
        raise ValueError(f"registry에 설정된 city_filter_col '{col}'이 파일 컬럼에 없습니다.")

    return df[df[col].astype(str).str.contains(str(value), na=False)]


# ── 좌표 정제 ─────────────────────────────────────────────────────────────────


def _require_columns(df: pd.DataFrame, columns: list[Any]) -> None:
    for column in columns:
        if column not in df.columns:
            raise ValueError(f"registry에 설정된 컬럼 '{column}'이 파일 컬럼에 없습니다.")


def _valid_coordinate_mask(lat: pd.Series, lon: pd.Series) -> pd.Series:
    lat_num = pd.to_numeric(lat, errors="coerce")
    lon_num = pd.to_numeric(lon, errors="coerce")
    missing = lat.isna() | lon.isna()
    out_of_range = (
        lat_num.isna()
        | lon_num.isna()
        | (lat_num < -90)
        | (lat_num > 90)
        | (lon_num < -180)
        | (lon_num > 180)
    )
    return (~missing) & (~out_of_range)


def _seoul_mask(lat: pd.Series, lon: pd.Series) -> pd.Series:
    lat_num = pd.to_numeric(lat, errors="coerce")
    lon_num = pd.to_numeric(lon, errors="coerce")
    return lat_num.between(*SEOUL_LAT_RANGE) & lon_num.between(*SEOUL_LON_RANGE)


def clean_coordinates(df: pd.DataFrame, entry: dict[str, Any], *, drop_seoul_outliers: bool = True) -> pd.DataFrame:
    """
    geometry 설정에 맞는 좌표 컬럼으로 결측/invalid 행을 제거합니다.

    drop_seoul_outliers가 True이면 서울 bbox 밖 좌표(LINESTRING은 시작 좌표 기준)도 제거합니다.
    """
    geometry = entry.get("geometry")

    if geometry == "POINT":
        lat_col, lon_col = entry.get("lat_col"), entry.get("lon_col")
        _require_columns(df, [lat_col, lon_col])
        mask = _valid_coordinate_mask(df[lat_col], df[lon_col])
        if drop_seoul_outliers:
            mask &= _seoul_mask(df[lat_col], df[lon_col])
        return df[mask]

    if geometry == "LINESTRING":
        start_lat_col, start_lon_col = entry.get("start_lat_col"), entry.get("start_lon_col")
        end_lat_col, end_lon_col = entry.get("end_lat_col"), entry.get("end_lon_col")
        _require_columns(df, [start_lat_col, start_lon_col, end_lat_col, end_lon_col])
        mask = _valid_coordinate_mask(df[start_lat_col], df[start_lon_col]) & _valid_coordinate_mask(
            df[end_lat_col], df[end_lon_col]
        )
        if drop_seoul_outliers:
            mask &= _seoul_mask(df[start_lat_col], df[start_lon_col])
        return df[mask]

    raise UnsupportedGeometryError(
        f"지원하지 않는 geometry입니다: {geometry!r} (지원: {sorted(SUPPORTED_GEOMETRY_TYPES)})"
    )


# ── 표준 record 생성 ──────────────────────────────────────────────────────────


def _clean_name(value: Any) -> Any:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return value


def build_records(df: pd.DataFrame, entry: dict[str, Any], dataset_key: str) -> list[dict[str, Any]]:
    """
    정제된 DataFrame과 registry entry로 표준 record 목록을 만듭니다.

    record 형태:
        {
            "dataset_key": ...,
            "name": ...,
            "geometry_type": "POINT" | "LINESTRING",
            "wkt": "...",
            "properties": {feature, score_column, score_effect, ai_expression},
        }
    """
    geometry = entry.get("geometry")
    name_col = entry.get("name_col")
    properties = {
        "feature": entry.get("feature"),
        "score_column": entry.get("score_column"),
        "score_effect": entry.get("score_effect"),
        "ai_expression": entry.get("ai_expression"),
    }

    records: list[dict[str, Any]] = []

    if geometry == "POINT":
        lat_col, lon_col = entry["lat_col"], entry["lon_col"]
        for _, row in df.iterrows():
            lat, lon = float(row[lat_col]), float(row[lon_col])
            records.append(
                {
                    "dataset_key": dataset_key,
                    "name": _clean_name(row.get(name_col)) if name_col else None,
                    "geometry_type": "POINT",
                    "wkt": f"POINT({lon} {lat})",
                    "properties": dict(properties),
                }
            )
        return records

    if geometry == "LINESTRING":
        start_lat_col, start_lon_col = entry["start_lat_col"], entry["start_lon_col"]
        end_lat_col, end_lon_col = entry["end_lat_col"], entry["end_lon_col"]
        for _, row in df.iterrows():
            start_lat, start_lon = float(row[start_lat_col]), float(row[start_lon_col])
            end_lat, end_lon = float(row[end_lat_col]), float(row[end_lon_col])
            records.append(
                {
                    "dataset_key": dataset_key,
                    "name": _clean_name(row.get(name_col)) if name_col else None,
                    "geometry_type": "LINESTRING",
                    "wkt": f"LINESTRING({start_lon} {start_lat}, {end_lon} {end_lat})",
                    "properties": dict(properties),
                }
            )
        return records

    raise UnsupportedGeometryError(
        f"지원하지 않는 geometry입니다: {geometry!r} (지원: {sorted(SUPPORTED_GEOMETRY_TYPES)})"
    )


# ── 전체 loader ────────────────────────────────────────────────────────────────


def load_configured_dataset(
    dataset_key: str,
    *,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    raw_dir: Path = DEFAULT_RAW_DIR,
    drop_seoul_outliers: bool = True,
) -> dict[str, Any]:
    """
    registry.yaml 설정만으로 configured dataset을 읽고 정제해 표준 record를 만듭니다.

    DB는 변경하지 않습니다. 반환값에는 각 단계별 행 수와 records가 포함됩니다.
    """
    registry = load_registry(registry_path)
    entry = get_approved_configured_dataset(registry, dataset_key)

    file_path = raw_dir / entry["file"]
    if not file_path.exists():
        raise FileNotFoundError(f"원본 파일을 찾을 수 없습니다: {file_path}")

    df, _ = read_dataset(file_path)
    original_rows = len(df)

    df = apply_city_filter(df, entry)
    after_city_filter_rows = len(df)

    df = clean_coordinates(df, entry, drop_seoul_outliers=drop_seoul_outliers)
    after_coordinate_cleanup_rows = len(df)

    records = build_records(df, entry, dataset_key)

    return {
        "dataset_key": dataset_key,
        "file": entry["file"],
        "original_rows": original_rows,
        "after_city_filter_rows": after_city_filter_rows,
        "after_coordinate_cleanup_rows": after_coordinate_cleanup_rows,
        "geometry_type": entry.get("geometry"),
        "records": records,
    }
