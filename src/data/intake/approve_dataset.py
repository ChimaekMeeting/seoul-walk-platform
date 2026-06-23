"""
src/data/intake/approve_dataset.py
draft_dataset.py로 등록된 draft(approved: false) dataset을 팀 결정에 따라
approved: true로 승격하는 CLI.

registry.yaml의 approved/approved_at/decision/reason을 갱신하고,
docs/data_intake_records.md의 해당 dataset_key 섹션에 승인 기록을 추가한다.
DB 적재나 source/collector 코드는 건드리지 않는다. 실제 적재는 별도 ingest
단계(예: python -m src.data.ingest)에서 approved: true인 dataset만 대상으로
수행한다.

실행 예:
    python -m src.data.intake.approve_dataset street_tree \\
        --decision "nature_score로 반영" \\
        --reason "가로수길은 자연친화 근거로 사용 가능하지만 그늘 보장은 어려워 shade_score는 보류"
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Any

from src.data.intake.draft_dataset import (
    DEFAULT_RECORDS_PATH,
    RECORDS_DOC_HEADER,
    render_record_section,
    validate_dataset_key,
)
from src.data.intake.registry import (
    DEFAULT_REGISTRY_PATH,
    RegistryUnavailableError,
    load_registry,
    save_registry,
)


class DatasetNotFoundError(ValueError):
    """registry.yaml에 dataset_key가 없을 때 발생합니다."""


class AlreadyApprovedError(ValueError):
    """이미 approved: true인 dataset을 force 없이 다시 승인하려 할 때 발생합니다."""


# ── 순수 함수 ────────────────────────────────────────────────────────────────


def get_dataset_or_raise(registry: dict[str, Any], dataset_key: str) -> dict[str, Any]:
    """registry["datasets"]에서 dataset_key를 찾습니다. 없으면 DatasetNotFoundError입니다."""
    datasets = registry.get("datasets") or {}
    if dataset_key not in datasets:
        raise DatasetNotFoundError(
            f"dataset_key '{dataset_key}'를 registry.yaml에서 찾을 수 없습니다. "
            "draft_dataset.py로 먼저 등록하세요."
        )
    return datasets[dataset_key]


def approve_dataset_entry(
    entry: dict[str, Any],
    *,
    decision: str,
    reason: str,
    approved_at: str,
    force: bool = False,
) -> dict[str, Any]:
    """
    dataset entry를 approved: true로 승격한 새 dict를 반환합니다(원본 entry는 변경하지 않음).

    layer/score/profile 값은 그대로 유지하고 approved/approved_at/decision/reason만
    덧붙입니다. 이미 approved: true이고 force가 아니면 AlreadyApprovedError를
    발생시킵니다.
    """
    if entry.get("approved") is True and not force:
        raise AlreadyApprovedError(
            "이미 approved: true인 dataset입니다. 다시 승인 기록을 남기려면 --force 옵션을 사용하세요."
        )

    updated = dict(entry)
    updated["approved"] = True
    updated["approved_at"] = approved_at
    updated["decision"] = decision
    updated["reason"] = reason
    return updated


def render_decision_block(*, decision: str, reason: str, approved_at: str) -> str:
    """docs 섹션 안에 끼워 넣을 승인 결정 기록(마크다운) 블록을 만듭니다."""
    return (
        f"### 승인 기록 ({approved_at})\n"
        f"- decision: {decision}\n"
        f"- reason: {reason}\n"
        "- approved: true\n"
    )


def upsert_decision_record(
    doc_path: Path,
    dataset_key: str,
    dataset_entry: dict[str, Any],
    decision_block: str,
) -> str:
    """
    docs/data_intake_records.md의 dataset_key 섹션 안에 decision_block을 추가합니다.

    섹션이 이미 있으면 end marker 바로 앞에 decision_block을 끼워 넣어 기존
    검수 기록은 그대로 유지합니다. 섹션이 아직 없으면(예: registry.yaml에 직접
    추가된 dataset) registry entry만으로 최소 섹션을 새로 만든 뒤
    decision_block을 덧붙입니다.

    반환값은 "appended_to_existing" / "created_with_decision" 중 하나입니다.
    """
    start_marker = f"<!-- intake-record:{dataset_key}:start -->"
    end_marker = f"<!-- intake-record:{dataset_key}:end -->"

    if not doc_path.exists():
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(RECORDS_DOC_HEADER, encoding="utf-8")

    text = doc_path.read_text(encoding="utf-8")

    if start_marker not in text:
        base_section = render_record_section(dataset_key, dataset_entry, {})
        section_with_decision = base_section.replace(
            end_marker, decision_block.rstrip("\n") + "\n" + end_marker
        )
        if not text.endswith("\n"):
            text += "\n"
        text = text + "\n" + section_with_decision.strip() + "\n"
        doc_path.write_text(text, encoding="utf-8")
        return "created_with_decision"

    end_idx = text.index(end_marker)
    text = text[:end_idx] + decision_block.rstrip("\n") + "\n" + text[end_idx:]
    doc_path.write_text(text, encoding="utf-8")
    return "appended_to_existing"


# ── CLI ──────────────────────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="draft(approved: false) 상태의 dataset을 approved: true로 승격합니다.",
    )
    parser.add_argument("dataset_key", help="승인할 dataset_key (registry.yaml에 draft로 등록되어 있어야 합니다)")
    parser.add_argument("--decision", required=True, help="팀 결정 내용 (예: 'nature_score로 반영')")
    parser.add_argument("--reason", required=True, help="결정 이유")
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY_PATH,
        help=f"registry.yaml 경로 (기본값: {DEFAULT_REGISTRY_PATH})",
    )
    parser.add_argument(
        "--records",
        type=Path,
        default=DEFAULT_RECORDS_PATH,
        help=f"data_intake_records.md 경로 (기본값: {DEFAULT_RECORDS_PATH})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="이미 approved: true인 dataset이어도 decision/reason/approved_at을 다시 기록합니다.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    approved_at = date.today().isoformat()

    try:
        dataset_key = validate_dataset_key(args.dataset_key)
        registry = load_registry(args.registry)
        entry = get_dataset_or_raise(registry, dataset_key)

        updated_entry = approve_dataset_entry(
            entry,
            decision=args.decision,
            reason=args.reason,
            approved_at=approved_at,
            force=args.force,
        )
        registry["datasets"][dataset_key] = updated_entry
        save_registry(registry, args.registry)
    except (RegistryUnavailableError, ValueError) as exc:
        print(str(exc))
        return 1

    decision_block = render_decision_block(
        decision=args.decision, reason=args.reason, approved_at=approved_at
    )
    doc_status = upsert_decision_record(args.records, dataset_key, updated_entry, decision_block)

    print("Dataset approved:")
    print(f"- dataset_key: {dataset_key}")
    print(f"- approved: {updated_entry['approved']}")
    print(f"- approved_at: {updated_entry['approved_at']}")
    print(f"- decision: {updated_entry['decision']}")
    print(f"- reason: {updated_entry['reason']}")
    print(f"- docs record ({args.records}): {doc_status}")
    print()
    print("이 명령은 DB를 변경하지 않습니다. 실제 적재는 별도 ingest 단계에서 수행합니다.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
