import argparse
import logging
import logging.config

from src.data.sources.osm_source import OSMSource
from src.data.sources.kakao_source import KakaoSource
from src.data.sources.public_source import PublicSource
from src.data.sources.csv_source import CSVSource

logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="외부·보조 RAW 데이터를 적재합니다.")
    parser.add_argument(
        "--scope",
        choices=("v1", "legacy-all"),
        default="v1",
        help="v1은 외부 RAW 적재를 건너뛰고, legacy-all만 기존 전체 RAW를 적재합니다.",
    )
    return parser.parse_args()


def collect_v1_sources() -> None:
    """
    현재 승인된 V1 원본은 로컬 도보 네트워크와 공원 Shapefile입니다.

    두 원본은 각 도메인 Collector가 직접 읽으므로 *_raw 선행 적재가 없습니다.
    """
    logger.info("V1은 외부·보조 RAW 자동 적재를 실행하지 않습니다.")


def collect_legacy_all_sources() -> None:
    """기존 전체 RAW 수집 파이프라인을 명시적으로 실행합니다."""
    logger.info("--- OSM raw 적재 ---")
    OSMSource().store()

    logger.info("--- Kakao raw 적재 ---")
    KakaoSource().store()

    logger.info("--- 공공데이터 raw 적재 ---")
    PublicSource().store()

    logger.info("--- CSV/XLSX raw 적재 ---")
    CSVSource().store()

    logger.info("✅ 모든 raw 데이터 적재 완료")


def collect(scope: str = "v1") -> None:
    if scope == "v1":
        collect_v1_sources()
        return
    if scope == "legacy-all":
        collect_legacy_all_sources()
        return
    raise ValueError(f"지원하지 않는 적재 범위: {scope}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] [%(name)s] %(message)s")
    args = parse_args()
    collect(scope=args.scope)
