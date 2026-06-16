import asyncio

from src.data import (
    BaseNetworkCollector,
    NatureCollector,
    SafetyCollector,
    LandmarkCollector,
    RunningCourseCollector,
    SlopeCalculator,
    ChildCollector
)

if __name__ == "__main__":
    # 이미 DB에 저장된 데이터 관련 collector는 주석 처리해주세요!
    # 실행 방법:
    # 1. python -m src.main                 # 테이블 생성
    # 2. python -m src.data.data_collector  # 데이터 적재

    base_collector = BaseNetworkCollector()
    nature_collector = NatureCollector()
    safety_collector = SafetyCollector()
    landmark_collector = LandmarkCollector()
    running_collector = RunningCourseCollector()
    slope_collector = SlopeCalculator()
    child_collector = ChildCollector()

    print("--- 도보 데이터 적재 ---")
    base_collector.save()

    print("--- 자연 데이터 적재 ---")
    nature_collector.save()

    print("--- 안전 데이터 적재 ---")
    safety_collector.save()

    # print("--- 경사로 데이터 적재 ---")
    # slope_collector.save()

    # print("--- 랜드마크 데이터 적재 ---")
    # asyncio.run(landmark_collector.save())

    print("--- 러닝 데이터 적재 ---")
    running_collector.save()

    print("--- 어린이 관련 시설 및 구역 데이터 적재 ---")
    child_collector.save()
