from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DIR = Path.home() / "Downloads"
DEFAULT_TARGET_DIR = PROJECT_ROOT / "src" / "data" / "raw"


@dataclass(frozen=True)
class RawDataset:
    filename: str
    required: bool
    used_by: str
    source_filenames: Sequence[str] = ()

    def candidates(self) -> tuple[str, ...]:
        return (self.filename, *self.source_filenames)


DATASETS = [
    RawDataset("전국어린이보호구역표준데이터.csv", True, "CSVSource protection_zone"),
    RawDataset("전국스마트가로등표준데이터.csv", True, "CSVSource streetlight"),
    RawDataset("전국자전거도로표준데이터.csv", True, "CSVSource bike_road"),
    RawDataset("서울시CCTV정보.xlsx", True, "CSVSource cctv"),
    RawDataset(
        "서울시 주요 공원현황.csv",
        True,
        "CSVSource running_park",
        ("서울시_주요_공원현황.csv",),
    ),
    RawDataset(
        "서울시 자치구별 도보 네트워크 공간정보.csv",
        True,
        "BaseNetworkCollector",
        ("서울시_자치구별_도보_네트워크_공간정보.csv",),
    ),
    RawDataset("전국가로수길정보표준데이터.csv", False, "future nature/tree layer"),
    RawDataset("서울 둘레길.csv", False, "future walking course layer", ("서울_둘레길.csv",)),
]


def stage_raw_data(source_dir: Path, target_dir: Path, overwrite: bool) -> int:
    target_dir.mkdir(parents=True, exist_ok=True)

    missing_required: list[str] = []
    missing_optional: list[str] = []

    for dataset in DATASETS:
        source = next(
            (source_dir / filename for filename in dataset.candidates() if (source_dir / filename).exists()),
            None,
        )
        target = target_dir / dataset.filename

        if source is None:
            if dataset.required:
                missing_required.append(dataset.filename)
            else:
                missing_optional.append(dataset.filename)
            continue

        if target.exists() and not overwrite:
            print(f"SKIP  {dataset.filename} already exists")
            continue

        shutil.copy2(source, target)
        print(f"COPY  {source.name} -> {target}")

    if missing_optional:
        print("\nOptional files not found:")
        for filename in missing_optional:
            print(f"- {filename}")

    if missing_required:
        print("\nRequired files not found:")
        for filename in missing_required:
            print(f"- {filename}")
        return 1

    print("\nRaw data files are ready.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy public raw data files into src/data/raw before DB ingestion.",
    )
    parser.add_argument(
        "--from-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help=f"Directory containing downloaded raw files. Default: {DEFAULT_SOURCE_DIR}",
    )
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=DEFAULT_TARGET_DIR,
        help=f"Directory used by CSVSource. Default: {DEFAULT_TARGET_DIR}",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite files that already exist in the target directory.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(stage_raw_data(args.from_dir, args.target_dir, args.overwrite))
