import argparse
import logging

from src.data import (
    BaseNetworkCollector,
    NatureCollector,
    SafetyCollector,
    LandmarkCollector,
    RunningCourseCollector,
    SlopeCalculator,
    ChildCollector,
    SeoulBoundaryCollector,
    SeoulWaterCollector,
)

logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="서비스용 도메인 데이터를 적재합니다.")
    parser.add_argument(
        "--network-mode",
        choices=("upsert", "rebuild"),
        default="upsert",
        help="upsert는 기존 score를 보존하고, rebuild는 네트워크 전체를 교체합니다.",
    )
    return parser.parse_args()


def collect(network_mode: str = "upsert") -> None:
    # 실행 순서:
    # 1. python -m src.main                    # 테이블 생성
    # 2. python -m src.data.source_collector   # raw 데이터 적재
    # 3. python -m src.data.data_collector --network-mode upsert|rebuild
    #
    # 각 collector는 layer 테이블이 이미 채워진 경우 자동 스킵됩니다.
    #
    network_collector = BaseNetworkCollector()
    if network_mode == "upsert":
        logger.info("--- 도보 네트워크 증분 갱신(upsert) ---")
        network_collector.upsert()
    elif network_mode == "rebuild":
        logger.warning("--- 도보 네트워크 전체 재구축(rebuild) ---")
        network_collector.rebuild()
    else:
        raise ValueError(f"지원하지 않는 네트워크 적재 모드: {network_mode}")

    logger.info("--- 자연 데이터 적재 ---")
    NatureCollector().save()

    logger.info("--- 안전 데이터 적재 ---")
    SafetyCollector().save()

    logger.info("--- 어린이 시설 적재 ---")
    ChildCollector().save()

    logger.info("--- 서울 행정구역 경계 적재 ---")
    SeoulBoundaryCollector().save()

    logger.info("--- 서울 수계 폴리곤 적재 ---")
    SeoulWaterCollector().save()

    # logger.info("--- 경사로 적재 ---")
    # SlopeCalculator().save()

    logger.info("--- 랜드마크 적재 ---")
    LandmarkCollector().save()

    # logger.info("--- 러닝 데이터 적재 ---")
    # RunningCourseCollector().save()

    logger.info("--- 사고 다발지역 적재 ---")
    SafetyCollector().update_accident()

    logger.info("--- 실외운동기구 적재 ---")
    RunningCourseCollector().update_outdoor_exercise()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] [%(name)s] %(message)s")
    args = parse_args()
    collect(network_mode=args.network_mode)
