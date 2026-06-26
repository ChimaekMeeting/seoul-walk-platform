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

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] [%(name)s] %(message)s")

    # 실행 순서:
    # 1. python -m src.main                    # 테이블 생성
    # 2. python -m src.data.source_collector   # raw 데이터 적재
    # 3. python -m src.data.data_collector     # 도메인 데이터 적재  ← 여기
    #
    # 각 collector는 layer 테이블이 이미 채워진 경우 자동 스킵됩니다.
    #
    logger.info("--- 도보 네트워크 적재 ---")
    BaseNetworkCollector().save()

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