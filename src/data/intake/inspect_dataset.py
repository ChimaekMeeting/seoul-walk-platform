"""
src/data/intake/inspect_dataset.py
신규 데이터(CSV/XLSX) 검수용 intake inspector MVP.

실행 예:
    python -m src.data.intake.inspect_dataset src/data/raw/전국가로수길정보표준데이터.csv

이 도구는 layer/score/profile을 확정하지 않는다. 컬럼/좌표/품질 "후보"와
registry.yaml에 이미 승인된 내용을 그대로 보여주는 역할만 한다. 최종 승인은
src/data/registry.yaml의 approved 값으로만 관리한다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.intake.registry import (
    DEFAULT_REGISTRY_PATH,
    RegistryUnavailableError,
    find_dataset_by_file,
    load_registry,
)

# ── 후보 탐지 토큰 ────────────────────────────────────────────────────────────

LAT_SUBSTRINGS = ["위도", "latitude", "lat", "y좌표"]
LAT_EXACT = {"y"}

LON_SUBSTRINGS = ["경도", "longitude", "lon", "lng", "x좌표"]
LON_EXACT = {"x"}

ADDRESS_SUBSTRINGS = ["주소", "addr", "address"]
NAME_SUBSTRINGS = ["이름", "명칭", "명", "title", "name"]

START_TOKENS = ["기점", "시작", "start"]
END_TOKENS = ["종점", "종료", "end"]

SEOUL_LAT_RANGE = (37.4, 37.7)
SEOUL_LON_RANGE = (126.7, 127.2)


# ── 파일 읽기 ────────────────────────────────────────────────────────────────


def read_dataset(path: Path) -> tuple[pd.DataFrame, str]:
    """
    CSV/XLSX 파일을 읽어 (DataFrame, source_type)을 반환합니다.

    CSV는 cp949 → utf-8 순서로 읽기를 시도합니다(src/data/sources/csv_source.py와 동일한 규칙).
    """
    suffix = path.suffix.lower()

    if suffix == ".csv":
        try:
            return pd.read_csv(path, encoding="cp949"), "csv"
        except UnicodeDecodeError:
            return pd.read_csv(path, encoding="utf-8"), "csv"

    if suffix == ".xlsx":
        return pd.read_excel(path, engine="openpyxl"), "xlsx"

    raise ValueError(f"지원하지 않는 파일 형식입니다: '{suffix}' (csv, xlsx만 지원)")


# ── 후보 탐지 ────────────────────────────────────────────────────────────────


def _matches(column: str, substrings: list[str], exact: set[str] | None = None) -> bool:
    lowered = column.lower()
    if exact and lowered in exact:
        return True
    return any(token in lowered for token in substrings)


def detect_lat_lon_candidates(columns: list[str]) -> tuple[list[str], list[str]]:
    """컬럼명 기반으로 위도/경도 후보를 탐지합니다."""
    lat_candidates = [c for c in columns if _matches(c, LAT_SUBSTRINGS, LAT_EXACT)]
    lon_candidates = [c for c in columns if _matches(c, LON_SUBSTRINGS, LON_EXACT)]
    return lat_candidates, lon_candidates


def detect_address_name_candidates(columns: list[str]) -> tuple[list[str], list[str]]:
    """컬럼명 기반으로 주소/이름 후보를 탐지합니다."""
    address_candidates = [c for c in columns if _matches(c, ADDRESS_SUBSTRINGS)]
    name_candidates = [c for c in columns if _matches(c, NAME_SUBSTRINGS)]
    return address_candidates, name_candidates


def estimate_geometry_candidate(
    columns: list[str],
    lat_candidates: list[str],
    lon_candidates: list[str],
) -> str:
    """
    geometry 후보를 추정합니다.

    - WKT/geometry 컬럼이 있으면 "WKT/GEOMETRY"
    - 기점/시작 + 종점/종료 패턴의 좌표 컬럼이 있으면 "LINESTRING"
    - lat/lon 후보가 모두 있으면 "POINT"
    - 그 외에는 "unknown"
    """
    lowered_columns = [c.lower() for c in columns]
    if any("wkt" in c or "geometry" in c for c in lowered_columns):
        return "WKT/GEOMETRY"

    coordinate_columns = lat_candidates + lon_candidates
    has_start = any(any(token in c for token in START_TOKENS) for c in coordinate_columns)
    has_end = any(any(token in c for token in END_TOKENS) for c in coordinate_columns)
    if has_start and has_end:
        return "LINESTRING"

    if lat_candidates and lon_candidates:
        return "POINT"

    return "unknown"


# ── 좌표 품질 검수 ────────────────────────────────────────────────────────────


def compute_coordinate_quality(df: pd.DataFrame, lat_col: str, lon_col: str) -> dict[str, int]:
    """
    lat_col/lon_col 기준으로 결측/이상/중복/서울 bbox 이탈 좌표 개수를 계산합니다.
    """
    lat_raw = df[lat_col]
    lon_raw = df[lon_col]

    missing_mask = lat_raw.isna() | lon_raw.isna()

    lat_num = pd.to_numeric(lat_raw, errors="coerce")
    lon_num = pd.to_numeric(lon_raw, errors="coerce")

    out_of_range = (
        lat_num.isna()
        | lon_num.isna()
        | (lat_num < -90)
        | (lat_num > 90)
        | (lon_num < -180)
        | (lon_num > 180)
    )
    invalid_mask = (~missing_mask) & out_of_range

    valid_mask = (~missing_mask) & (~invalid_mask)
    valid_coords = df.loc[valid_mask, [lat_col, lon_col]]
    duplicate_count = int(valid_coords.duplicated(subset=[lat_col, lon_col]).sum())

    in_seoul = (
        lat_num.between(*SEOUL_LAT_RANGE)
        & lon_num.between(*SEOUL_LON_RANGE)
    )
    outlier_count = int((valid_mask & ~in_seoul).sum())

    return {
        "missing_coordinates": int(missing_mask.sum()),
        "invalid_coordinates": int(invalid_mask.sum()),
        "duplicate_coordinates": duplicate_count,
        "seoul_bbox_outliers": outlier_count,
    }


# ── 리포트 조립 ──────────────────────────────────────────────────────────────


def build_report(path: Path, registry_path: Path = DEFAULT_REGISTRY_PATH) -> dict[str, Any]:
    df, source_type = read_dataset(path)
    columns = list(df.columns)

    lat_candidates, lon_candidates = detect_lat_lon_candidates(columns)
    address_candidates, name_candidates = detect_address_name_candidates(columns)
    geometry_candidate = estimate_geometry_candidate(columns, lat_candidates, lon_candidates)

    quality = None
    if lat_candidates and lon_candidates:
        quality = compute_coordinate_quality(df, lat_candidates[0], lon_candidates[0])

    registry_info: dict[str, Any]
    try:
        registry = load_registry(registry_path)
        dataset_key, dataset = find_dataset_by_file(registry, path.name)
        if dataset is None:
            registry_info = {
                "registry_status": "not_registered",
                "dataset_key": None,
                "approved": False,
                "layer": "undecided",
                "score_column": "undecided",
                "score_effect": "undecided",
                "profiles": [],
            }
        else:
            registry_info = {
                "registry_status": "registered",
                "dataset_key": dataset_key,
                "approved": dataset.get("approved", False),
                "layer": dataset.get("layer", "undecided"),
                "score_column": dataset.get("score_column", "undecided"),
                "score_effect": dataset.get("score_effect", "undecided"),
                "profiles": dataset.get("profiles", []),
            }
    except RegistryUnavailableError as exc:
        registry_info = {"registry_status": "unavailable", "error": str(exc)}

    return {
        "file": str(path),
        "source_type": source_type,
        "rows": len(df),
        "columns_count": len(columns),
        "columns": columns,
        "lat_candidates": lat_candidates,
        "lon_candidates": lon_candidates,
        "address_candidates": address_candidates,
        "name_candidates": name_candidates,
        "geometry_candidate": geometry_candidate,
        "quality": quality,
        "registry": registry_info,
    }


# ── 출력 ─────────────────────────────────────────────────────────────────────


def print_report(report: dict[str, Any]) -> None:
    print("[Intake Inspector]")
    print(f"file: {report['file']}")
    print(f"source_type: {report['source_type']}")
    print(f"rows: {report['rows']}")
    print(f"columns_count: {report['columns_count']}")

    print("\n[Candidates]")
    print(f"lat_candidates: {report['lat_candidates']}")
    print(f"lon_candidates: {report['lon_candidates']}")
    print(f"address_candidates: {report['address_candidates']}")
    print(f"name_candidates: {report['name_candidates']}")
    print(f"geometry_candidate: {report['geometry_candidate']}")

    print("\n[Quality]")
    if report["quality"] is None:
        print("lat/lon 후보가 없어 좌표 품질을 계산할 수 없습니다.")
    else:
        for key, value in report["quality"].items():
            print(f"{key}: {value}")

    print("\n[Registry]")
    registry = report["registry"]
    if registry.get("registry_status") == "unavailable":
        print(f"registry_status: unavailable ({registry.get('error')})")
    else:
        print(f"registry_status: {registry['registry_status']}")
        print(f"dataset_key: {registry['dataset_key']}")
        print(f"approved: {registry['approved']}")
        print(f"layer: {registry['layer']}")
        print(f"score_column: {registry['score_column']}")
        print(f"score_effect: {registry['score_effect']}")
        print(f"profiles: {registry['profiles']}")


# ── CLI ──────────────────────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="신규 CSV/XLSX 데이터의 구조와 품질을 적재 전에 검수합니다.",
    )
    parser.add_argument("path", type=Path, help="검수할 CSV/XLSX 파일 경로")
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY_PATH,
        help=f"registry.yaml 경로 (기본값: {DEFAULT_REGISTRY_PATH})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.path.exists():
        print(f"파일을 찾을 수 없습니다: {args.path}")
        return 1

    try:
        report = build_report(args.path, registry_path=args.registry)
    except ValueError as exc:
        print(str(exc))
        return 1

    print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
