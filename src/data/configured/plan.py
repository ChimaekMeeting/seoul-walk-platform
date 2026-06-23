"""
src/data/configured/plan.py
approved: true, dataset_type: configured인 dataset을 실제 DB(csv_raw/layer/score)에
쓰기 전에, raw/layer/score/profile 반영 계획과 schema 충돌 가능성을 출력하는 CLI.

preview.py는 정제된 record를 보여주고, plan.py는 그 record를 실제 파이프라인
(csv_raw -> layer -> score -> profile)에 연결하기 위해 무엇이 필요하고 어떤
위험이 있는지를 보여준다. 이 명령은 DB를 변경하지 않는다. 실제 적재는 별도
ingest 단계에서 수행한다.

실행 예:
    python -m src.data.configured.plan street_tree
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from src.data.configured.configured_dataset import (
    DEFAULT_RAW_DIR,
    get_approved_configured_dataset,
    infer_target_layer,
    load_configured_dataset,
)
from src.data.intake.registry import DEFAULT_REGISTRY_PATH, RegistryUnavailableError, load_registry

# layer가 현재 가지고 있는 raw FK 컬럼. plan.py가 schema 충돌 여부를 판단할 때 사용한다.
LAYER_RAW_ID_COLUMNS = {
    "nature_layer": ["osm_raw_id"],
    "safety_layer": ["csv_raw_id"],
    "running_layer": ["csv_raw_id"],
    "child_layer": ["csv_raw_id", "public_raw_id"],
    "landmark_layer": [],
}

# raw_table -> 해당 raw를 참조하는 FK 컬럼명.
RAW_TABLE_TO_ID_COLUMN = {
    "csv_raw": "csv_raw_id",
    "osm_raw": "osm_raw_id",
    "public_raw": "public_raw_id",
}

# layer가 데이터 종류를 구분하는 컬럼(있는 경우). 권장안 문구에 사용한다.
LAYER_DISCRIMINATOR_COLUMNS = {
    "nature_layer": "green_type",
}

CONFIGURED_SOURCE_RAW_TABLE = "csv_raw"


# ── Raw Plan ─────────────────────────────────────────────────────────────────


def build_raw_plan(dataset_key: str, entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "raw_table": CONFIGURED_SOURCE_RAW_TABLE,
        "query_key": f"type={dataset_key}",
        "source_file": entry.get("file"),
        "geometry": entry.get("geometry"),
    }


# ── Layer Plan ────────────────────────────────────────────────────────────────


def build_layer_plan(entry: dict[str, Any]) -> dict[str, Any]:
    score_column = entry.get("score_column")
    target_layer = infer_target_layer(score_column)
    expected_source_ref = RAW_TABLE_TO_ID_COLUMN[CONFIGURED_SOURCE_RAW_TABLE]

    if target_layer == "undecided":
        compatibility = "unknown"
        layer_current_source_ref = "n/a"
    else:
        existing_columns = LAYER_RAW_ID_COLUMNS.get(target_layer, [])
        if expected_source_ref in existing_columns:
            compatibility = "ok"
            layer_current_source_ref = expected_source_ref
        else:
            compatibility = "warning"
            layer_current_source_ref = ", ".join(existing_columns) if existing_columns else "none"

    return {
        "target_layer": target_layer,
        "feature": entry.get("feature"),
        "source_raw_table": CONFIGURED_SOURCE_RAW_TABLE,
        "expected_source_ref": expected_source_ref,
        "layer_current_source_ref": layer_current_source_ref,
        "compatibility": compatibility,
    }


def build_schema_warnings(dataset_key: str, layer_plan: dict[str, Any]) -> list[str]:
    """layer_plan의 compatibility가 warning일 때 schema 충돌 경고 문구를 만듭니다."""
    if layer_plan["compatibility"] != "warning":
        return []

    target_layer = layer_plan["target_layer"]
    current_ref = layer_plan["layer_current_source_ref"]
    discriminator = LAYER_DISCRIMINATOR_COLUMNS.get(target_layer)

    if discriminator:
        recommendation = (
            f"권장안: {target_layer}에 csv_raw_id nullable 컬럼을 추가한 뒤 "
            f"{discriminator}='{dataset_key}'로 저장한다."
        )
    else:
        recommendation = (
            f"권장안: {target_layer}에 csv_raw_id nullable 컬럼을 추가한 뒤 "
            f"적절한 구분 컬럼에 '{dataset_key}'를 기록한다."
        )

    return [
        f"{dataset_key}는 csv_raw 기반 configured dataset이다.",
        f"{target_layer}는 현재 {current_ref}만 가지고 있다.",
        f"source 추적을 유지하려면 {target_layer}에 csv_raw_id nullable 컬럼을 추가하거나, "
        "raw id 없이 저장하거나, "
        f"{dataset_key}_layer를 별도로 만들어야 한다.",
        recommendation,
    ]


# ── Score Plan ────────────────────────────────────────────────────────────────


def build_score_plan(entry: dict[str, Any], geometry_type: str | None) -> dict[str, Any]:
    score_column = entry.get("score_column")
    warnings: list[str] = []

    if score_column == "nature_score":
        warnings.append("현재 NatureRepository.get_nature_h3_counts()는 geom centroid 기반이다.")
    if geometry_type == "LINESTRING":
        warnings.append("LINESTRING 데이터는 선 전체가 아니라 중심점 기준으로 반영될 수 있다.")

    return {
        "score_column": score_column,
        "score_effect": entry.get("score_effect"),
        "update_method": "H3 log normalization",
        "warnings": warnings,
    }


# ── Profile Plan ──────────────────────────────────────────────────────────────


def build_profile_plan(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "profiles": list(entry.get("profiles") or []),
        "note": "profile은 score 조합이며 healing_layer/healing_score를 자동 생성하지 않는다.",
        "warning": "profiles.py에 해당 profile이 실제로 존재하는지는 별도 확인이 필요하다.",
    }


# ── AI Expression Plan ────────────────────────────────────────────────────────


def build_ai_expression_plan(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "allowed": entry.get("ai_expression"),
        "note": '"그늘 많은 길을 보장"처럼 데이터 근거가 부족한 표현은 사용하지 않는다.',
    }


# ── 결정 항목 ──────────────────────────────────────────────────────────────────


def build_decision_items(dataset_key: str, layer_plan: dict[str, Any], geometry_type: str | None) -> list[str]:
    items: list[str] = []
    if layer_plan["compatibility"] == "warning":
        target_layer = layer_plan["target_layer"]
        items.append(f"{target_layer}에 csv_raw_id를 추가할지")
        items.append(f"raw id 없이 {target_layer}에 저장할지")
        items.append(f"{dataset_key}_layer를 별도로 만들지")
    if geometry_type == "LINESTRING":
        items.append("LINESTRING H3 집계를 centroid로 우선 처리할지, 선 샘플링으로 개선할지")
    return items


# ── 전체 plan 조립 (순수 데이터 구조, DB 미사용) ──────────────────────────────


def build_plan(
    dataset_key: str,
    *,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    raw_dir: Path = DEFAULT_RAW_DIR,
    drop_seoul_outliers: bool = True,
) -> dict[str, Any]:
    """approved configured dataset의 raw/layer/score/profile 반영 계획을 만듭니다.

    registry.yaml과 원본 파일만 읽으며 DB에는 전혀 접근하지 않습니다.
    """
    registry = load_registry(registry_path)
    entry = get_approved_configured_dataset(registry, dataset_key)

    load_result = load_configured_dataset(
        dataset_key,
        registry_path=registry_path,
        raw_dir=raw_dir,
        drop_seoul_outliers=drop_seoul_outliers,
    )
    geometry_type = load_result["geometry_type"]

    raw_plan = build_raw_plan(dataset_key, entry)
    layer_plan = build_layer_plan(entry)
    schema_warnings = build_schema_warnings(dataset_key, layer_plan)
    score_plan = build_score_plan(entry, geometry_type)
    profile_plan = build_profile_plan(entry)
    ai_expression_plan = build_ai_expression_plan(entry)
    decision_items = build_decision_items(dataset_key, layer_plan, geometry_type)

    return {
        "dataset_key": dataset_key,
        "original_rows": load_result["original_rows"],
        "after_city_filter_rows": load_result["after_city_filter_rows"],
        "after_coordinate_cleanup_rows": load_result["after_coordinate_cleanup_rows"],
        "records_count": len(load_result["records"]),
        "geometry_type": geometry_type,
        "raw_plan": raw_plan,
        "layer_plan": layer_plan,
        "schema_warnings": schema_warnings,
        "score_plan": score_plan,
        "profile_plan": profile_plan,
        "ai_expression_plan": ai_expression_plan,
        "decision_items": decision_items,
    }


# ── 출력 ──────────────────────────────────────────────────────────────────────


def print_plan(plan: dict[str, Any]) -> None:
    print(f"dataset_key: {plan['dataset_key']}")
    print(f"original_rows: {plan['original_rows']}")
    print(f"after_city_filter_rows: {plan['after_city_filter_rows']}")
    print(f"after_coordinate_cleanup_rows: {plan['after_coordinate_cleanup_rows']}")
    print(f"records_count: {plan['records_count']}")
    print(f"geometry_type: {plan['geometry_type']}")

    print("\n[Raw Plan]")
    for key, value in plan["raw_plan"].items():
        print(f"- {key}: {value}")

    print("\n[Layer Plan]")
    for key, value in plan["layer_plan"].items():
        print(f"- {key}: {value}")

    if plan["schema_warnings"]:
        print("\n[Schema Warning]")
        for warning in plan["schema_warnings"]:
            print(f"- {warning}")

    print("\n[Score Plan]")
    score_plan = plan["score_plan"]
    print(f"- score_column: {score_plan['score_column']}")
    print(f"- score_effect: {score_plan['score_effect']}")
    print(f"- update_method: {score_plan['update_method']}")
    for warning in score_plan["warnings"]:
        print(f"- warning: {warning}")

    print("\n[Profile Plan]")
    profile_plan = plan["profile_plan"]
    profiles = ", ".join(profile_plan["profiles"]) if profile_plan["profiles"] else "none"
    print(f"- profiles: {profiles}")
    print(f"- note: {profile_plan['note']}")
    print(f"- warning: {profile_plan['warning']}")

    print("\n[AI Expression]")
    ai_expression_plan = plan["ai_expression_plan"]
    print(f"- allowed: {ai_expression_plan['allowed']}")
    print(f"- note: {ai_expression_plan['note']}")

    print()
    print("이 명령은 DB를 변경하지 않습니다.")
    if plan["decision_items"]:
        print("실제 반영 전 다음 결정을 해야 합니다:")
        for index, item in enumerate(plan["decision_items"], start=1):
            print(f"{index}. {item}")


# ── CLI ──────────────────────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="approved configured dataset의 raw/layer/score/profile 반영 계획과 schema 충돌 가능성을 출력합니다.",
    )
    parser.add_argument("dataset_key", help="계획을 볼 dataset_key (registry.yaml에 approved: true로 등록되어 있어야 합니다)")
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY_PATH,
        help=f"registry.yaml 경로 (기본값: {DEFAULT_REGISTRY_PATH})",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=DEFAULT_RAW_DIR,
        help=f"원본 파일이 있는 디렉터리 (기본값: {DEFAULT_RAW_DIR})",
    )
    parser.add_argument(
        "--keep-seoul-outliers",
        action="store_true",
        help="서울 bbox 밖 좌표도 제거하지 않고 그대로 둡니다.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        plan = build_plan(
            args.dataset_key,
            registry_path=args.registry,
            raw_dir=args.raw_dir,
            drop_seoul_outliers=not args.keep_seoul_outliers,
        )
    except (ValueError, FileNotFoundError, RegistryUnavailableError) as exc:
        print(str(exc))
        return 1

    print_plan(plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
