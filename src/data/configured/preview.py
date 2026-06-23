"""
src/data/configured/preview.py
approved: true, dataset_type: configured인 dataset을 DB에 적재하기 전에
registry.yaml 설정만으로 읽고 정제한 결과를 미리 확인하는 CLI.

이 명령은 DB를 변경하지 않는다. csv_raw 적재와 layer/score 반영은 다음
ingest 단계에서 구현한다.

실행 예:
    python -m src.data.configured.preview street_tree
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.data.configured.configured_dataset import (
    DEFAULT_RAW_DIR,
    load_configured_dataset,
)
from src.data.intake.registry import DEFAULT_REGISTRY_PATH, RegistryUnavailableError

SAMPLE_SIZE = 5


def print_preview(result: dict) -> None:
    print(f"dataset_key: {result['dataset_key']}")
    print(f"file: {result['file']}")
    print(f"original_rows: {result['original_rows']}")
    print(f"after_city_filter_rows: {result['after_city_filter_rows']}")
    print(f"after_coordinate_cleanup_rows: {result['after_coordinate_cleanup_rows']}")
    print(f"geometry_type: {result['geometry_type']}")

    print(f"\n[Sample records] (최대 {SAMPLE_SIZE}개, 전체 {len(result['records'])}개)")
    for record in result["records"][:SAMPLE_SIZE]:
        print(record)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="approved configured dataset을 registry 설정으로 읽고 정제한 결과를 미리 확인합니다.",
    )
    parser.add_argument("dataset_key", help="미리 볼 dataset_key (registry.yaml에 approved: true로 등록되어 있어야 합니다)")
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
        result = load_configured_dataset(
            args.dataset_key,
            registry_path=args.registry,
            raw_dir=args.raw_dir,
            drop_seoul_outliers=not args.keep_seoul_outliers,
        )
    except (ValueError, FileNotFoundError, RegistryUnavailableError) as exc:
        print(str(exc))
        return 1

    print_preview(result)
    print()
    print("이 명령은 DB를 변경하지 않습니다. csv_raw 적재와 layer/score 반영은 다음 ingest 단계에서 수행합니다.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
