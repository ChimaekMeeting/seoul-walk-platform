"""
src/data/intake/draft_dataset.py
inspect_dataset.py 결과를 바탕으로 registry.yaml에 draft(approved: false) 항목을
등록하는 대화형 CLI.

이 도구는 DB를 변경하지 않는다. layer/score/profile을 스스로 확정하지도 않으며,
사람이 입력한 내용을 "초안"으로 registry.yaml에 저장할 뿐이다. approved가 true가
되기 전까지는 source_collector/data_collector에 반영되지 않는다.

실행 예:
    python -m src.data.intake.draft_dataset src/data/raw/전국가로수길정보표준데이터.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from src.data.intake.inspect_dataset import build_report, print_report
from src.data.intake.registry import (
    DEFAULT_REGISTRY_PATH,
    RegistryUnavailableError,
    load_registry,
    save_registry,
)

NOTE_TEXT = "draft_dataset.py로 생성된 초안입니다. approved true 전까지 서비스에 반영하지 않습니다."
RECORD_DISCLAIMER = "이 기록은 draft이며 실제 적재/score/profile 반영이 아닙니다."

DEFAULT_RECORDS_PATH = Path("docs/data_intake_records.md")
RECORDS_DOC_HEADER = (
    "# 데이터 intake 기록\n"
    "\n"
    "draft_dataset.py가 registry.yaml에 draft를 등록할 때마다 자동으로 추가하는 기록입니다. "
    f"{RECORD_DISCLAIMER}\n"
)

DATASET_TYPE_CHOICES = {"configured", "adapter"}
SCORE_EFFECT_CHOICES = {"bonus", "penalty", "mode-specific", "none"}
QUALITY_FIELDS = [
    "missing_coordinates",
    "invalid_coordinates",
    "duplicate_coordinates",
    "seoul_bbox_outliers",
]

START_TOKENS = ["시작", "기점", "start"]
END_TOKENS = ["종료", "종점", "end"]


# ── 순수 함수 ────────────────────────────────────────────────────────────────


def coalesce(raw: str | None, default: Any) -> Any:
    """raw가 비어 있으면(None 또는 공백뿐) default를, 아니면 strip된 raw를 반환합니다."""
    if raw is None:
        return default
    stripped = raw.strip()
    return default if stripped == "" else stripped


def parse_profiles(raw: str) -> list[str]:
    """comma-separated 문자열을 profile 리스트로 변환합니다. 빈 문자열은 빈 리스트입니다."""
    if not raw or not raw.strip():
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


def first_or_none(candidates: list[str]) -> str | None:
    return candidates[0] if candidates else None


def first_matching_or_none(candidates: list[str], tokens: list[str]) -> str | None:
    for candidate in candidates:
        if any(token in candidate for token in tokens):
            return candidate
    return None


def ensure_overwrite_allowed(registry: dict[str, Any], dataset_key: str, overwrite: bool) -> None:
    """dataset_key가 이미 registry에 있는데 overwrite가 아니면 에러를 발생시킵니다."""
    datasets = registry.get("datasets") or {}
    if dataset_key in datasets and not overwrite:
        raise ValueError(
            f"dataset_key '{dataset_key}'는 이미 registry.yaml에 등록되어 있습니다. "
            "덮어쓰려면 --overwrite 옵션을 사용하세요."
        )


def validate_dataset_key(dataset_key: Any) -> str:
    """
    registry/docs에서 dataset을 식별할 key를 검증합니다.

    빈 값이 YAML의 null 키로 저장되면 데이터 계약을 추적할 수 없으므로
    dataset_key는 반드시 비어 있지 않은 문자열이어야 합니다.
    """
    if not isinstance(dataset_key, str) or not dataset_key.strip():
        raise ValueError("dataset_key는 필수입니다. 예: street_tree")
    return dataset_key.strip()


def build_dataset_entry(
    *,
    file_name: str,
    source_type: str,
    raw_table: str,
    answers: dict[str, Any],
) -> dict[str, Any]:
    """
    사용자 입력(answers)과 파일 메타데이터로 registry entry를 만듭니다.

    layer/score/profile을 자동으로 확정하지 않고 answers에 들어온 값을 그대로
    담는 순수 함수입니다. approved는 항상 False로 고정합니다.
    """
    dataset_type = answers["dataset_type"]

    entry: dict[str, Any] = {
        "approved": False,
        "dataset_type": dataset_type,
        "source_type": source_type,
        "file": file_name,
        "raw_table": raw_table,
        "feature": answers.get("feature"),
        "score_column": answers.get("score_column"),
        "score_effect": answers.get("score_effect"),
        "profiles": answers.get("profiles", []),
        "ai_expression": answers.get("ai_expression"),
    }

    if dataset_type == "configured":
        geometry = answers.get("geometry")
        entry["geometry"] = geometry
        if geometry == "LINESTRING":
            entry["start_lat_col"] = answers.get("start_lat_col")
            entry["start_lon_col"] = answers.get("start_lon_col")
            entry["end_lat_col"] = answers.get("end_lat_col")
            entry["end_lon_col"] = answers.get("end_lon_col")
        else:
            entry["lat_col"] = answers.get("lat_col")
            entry["lon_col"] = answers.get("lon_col")
        entry["city_filter_col"] = answers.get("city_filter_col")
        entry["city_filter_value"] = answers.get("city_filter_value")
        entry["name_col"] = answers.get("name_col")
        entry["address_col"] = answers.get("address_col")
    else:
        entry["adapter"] = answers.get("adapter")
        entry["collector"] = answers.get("collector")
        entry["layer"] = answers.get("layer")

    entry["note"] = NOTE_TEXT
    return entry


def render_record_section(dataset_key: str, entry: dict[str, Any], report: dict[str, Any]) -> str:
    """
    docs/data_intake_records.md에 append/갱신할 dataset_key 단위 섹션을 만듭니다.

    registry entry와 inspector report만으로 만들어지는 순수 함수입니다.
    """
    profiles = entry.get("profiles") or []

    city_filter_col = entry.get("city_filter_col")
    if city_filter_col:
        city_filter = f"{city_filter_col} = {entry.get('city_filter_value')}"
    else:
        city_filter = "none"

    lines = [
        f"<!-- intake-record:{dataset_key}:start -->",
        f"## {dataset_key}",
        "",
        f"- file: {entry.get('file')}",
        f"- approved: {entry.get('approved', False)}",
        f"- source_type: {entry.get('source_type')}",
        f"- geometry: {entry.get('geometry', 'n/a')}",
        f"- city_filter: {city_filter}",
        f"- score_column: {entry.get('score_column')}",
        f"- score_effect: {entry.get('score_effect')}",
        f"- profiles: {', '.join(profiles) if profiles else 'none'}",
        f"- ai_expression: {entry.get('ai_expression')}",
    ]

    if report.get("rows") is not None:
        lines.append(f"- rows: {report['rows']}")

    quality = report.get("quality") or {}
    for field in QUALITY_FIELDS:
        if field in quality:
            lines.append(f"- {field}: {quality[field]}")

    lines.append(f"- note: {RECORD_DISCLAIMER}")
    lines.append(f"<!-- intake-record:{dataset_key}:end -->")
    return "\n".join(lines)


def upsert_intake_record(
    doc_path: Path,
    dataset_key: str,
    section_text: str,
    overwrite: bool,
) -> str:
    """
    docs/data_intake_records.md에 dataset_key 섹션을 추가하거나 갱신합니다.

    파일이 없으면 새로 만듭니다. 같은 dataset_key 섹션이 이미 있으면 기본적으로
    건너뛰고, overwrite=True일 때만 그 섹션을 갱신합니다.
    반환값은 "appended" / "updated" / "skipped" 중 하나입니다.
    """
    start_marker = f"<!-- intake-record:{dataset_key}:start -->"
    end_marker = f"<!-- intake-record:{dataset_key}:end -->"

    if not doc_path.exists():
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(RECORDS_DOC_HEADER, encoding="utf-8")

    text = doc_path.read_text(encoding="utf-8")

    if start_marker in text:
        if not overwrite:
            return "skipped"
        start_idx = text.index(start_marker)
        end_idx = text.index(end_marker) + len(end_marker)
        text = text[:start_idx] + section_text.strip() + "\n" + text[end_idx:].lstrip("\n")
        doc_path.write_text(text, encoding="utf-8")
        return "updated"

    if not text.endswith("\n"):
        text += "\n"
    text = text + "\n" + section_text.strip() + "\n"
    doc_path.write_text(text, encoding="utf-8")
    return "appended"


# ── 대화형 입력 ──────────────────────────────────────────────────────────────


def _ask(prompt_text: str, default: Any = None) -> Any:
    suffix = f" [{default}]" if default not in (None, "", []) else ""
    raw = input(f"{prompt_text}{suffix}: ")
    return coalesce(raw, default)


def _ask_required(prompt_text: str) -> str:
    while True:
        try:
            return validate_dataset_key(_ask(prompt_text))
        except ValueError as exc:
            print(str(exc))


def _ask_choice(prompt_text: str, choices: set[str], default: str) -> str:
    value = _ask(prompt_text, default)
    while value not in choices:
        print(f"{'/'.join(sorted(choices))} 중 하나를 입력하세요: {value!r}")
        value = _ask(prompt_text, default)
    return value


def collect_answers(report: dict[str, Any]) -> dict[str, Any]:
    """터미널 입력을 받아 build_dataset_entry에 넘길 answers dict(+dataset_key)를 만듭니다."""
    lat_candidates = report["lat_candidates"]
    lon_candidates = report["lon_candidates"]
    name_candidates = report["name_candidates"]
    address_candidates = report["address_candidates"]
    geometry_candidate = report["geometry_candidate"]

    dataset_key = _ask_required("dataset_key")
    dataset_type = _ask_choice("dataset_type (configured/adapter)", DATASET_TYPE_CHOICES, "configured")
    feature = _ask("feature")
    score_column = _ask("score_column")
    score_effect = _ask_choice(
        "score_effect (bonus/penalty/mode-specific/none)", SCORE_EFFECT_CHOICES, "none"
    )
    profiles = parse_profiles(_ask("profiles (comma-separated)", ""))
    ai_expression = _ask("ai_expression")

    answers: dict[str, Any] = {
        "dataset_key": dataset_key,
        "dataset_type": dataset_type,
        "feature": feature,
        "score_column": score_column,
        "score_effect": score_effect,
        "profiles": profiles,
        "ai_expression": ai_expression,
    }

    if dataset_type == "configured":
        geometry = _ask("geometry", geometry_candidate)
        answers["geometry"] = geometry

        if geometry == "LINESTRING":
            start_lat_default = first_matching_or_none(lat_candidates, START_TOKENS) or first_or_none(lat_candidates)
            start_lon_default = first_matching_or_none(lon_candidates, START_TOKENS) or first_or_none(lon_candidates)
            end_lat_default = first_matching_or_none(lat_candidates, END_TOKENS)
            end_lon_default = first_matching_or_none(lon_candidates, END_TOKENS)
            answers["start_lat_col"] = _ask("start_lat_col", start_lat_default)
            answers["start_lon_col"] = _ask("start_lon_col", start_lon_default)
            answers["end_lat_col"] = _ask("end_lat_col", end_lat_default)
            answers["end_lon_col"] = _ask("end_lon_col", end_lon_default)
        else:
            answers["lat_col"] = _ask("lat_col", first_or_none(lat_candidates))
            answers["lon_col"] = _ask("lon_col", first_or_none(lon_candidates))

        answers["city_filter_col"] = _ask("city_filter_col")
        answers["city_filter_value"] = _ask("city_filter_value")
        answers["name_col"] = _ask("name_col", first_or_none(name_candidates))
        answers["address_col"] = _ask("address_col", first_or_none(address_candidates))
    else:
        answers["adapter"] = _ask("adapter")
        answers["collector"] = _ask("collector")
        answers["layer"] = _ask("layer")

    return answers


# ── CLI ──────────────────────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="inspect_dataset.py 결과를 바탕으로 registry.yaml에 draft 항목을 등록합니다.",
    )
    parser.add_argument("path", type=Path, help="등록할 CSV/XLSX 파일 경로")
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY_PATH,
        help=f"registry.yaml 경로 (기본값: {DEFAULT_REGISTRY_PATH})",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="dataset_key가 이미 registry.yaml에 있어도 덮어씁니다.",
    )
    parser.add_argument(
        "--records",
        type=Path,
        default=DEFAULT_RECORDS_PATH,
        help=f"data_intake_records.md 경로 (기본값: {DEFAULT_RECORDS_PATH})",
    )
    parser.add_argument(
        "--overwrite-doc",
        action="store_true",
        help="data_intake_records.md에 dataset_key 섹션이 이미 있어도 갱신합니다.",
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
    print()

    answers = collect_answers(report)
    dataset_key = answers.pop("dataset_key")

    try:
        registry = load_registry(args.registry)
        ensure_overwrite_allowed(registry, dataset_key, args.overwrite)

        entry = build_dataset_entry(
            file_name=args.path.name,
            source_type=report["source_type"],
            raw_table="csv_raw",
            answers=answers,
        )
        registry.setdefault("datasets", {})[dataset_key] = entry
        save_registry(registry, args.registry)
    except (RegistryUnavailableError, ValueError) as exc:
        print(str(exc))
        return 1

    record_section = render_record_section(dataset_key, entry, report)
    record_status = upsert_intake_record(args.records, dataset_key, record_section, args.overwrite_doc)

    print("Draft dataset saved:")
    print(f"- dataset_key: {dataset_key}")
    print(f"- approved: {entry['approved']}")
    print(f"- file: {entry['file']}")
    print(f"- score_column: {entry['score_column']}")
    print(f"- score_effect: {entry['score_effect']}")
    print(f"- docs record ({args.records}): {record_status}")
    print()
    print("Next:")
    if record_status == "skipped":
        print(
            f"1. {args.records}에 '{dataset_key}' 섹션이 이미 있어 자동 기록을 건너뛰었습니다. "
            "갱신하려면 --overwrite-doc 옵션을 사용하세요."
        )
    else:
        print(f"1. {args.records}에 자동 기록된 내용을 검수/판단 기록으로 확인하세요.")
    print(f"2. 팀 승인 후 python -m src.data.intake.approve_dataset {dataset_key} 를 실행하세요.")
    print("3. approved true 전까지 source_collector/data_collector에는 반영하지 않습니다.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
