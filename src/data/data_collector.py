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
    # 실행 순서:
    # 1. python -m src.main                    # 테이블 생성
    # 2. python -m src.data.source_collector   # raw 데이터 적재
    # 3. python -m src.data.data_collector     # 도메인 데이터 적재  ← 여기
    #
    # 각 collector는 layer 테이블이 이미 채워진 경우 자동 스킵됩니다.

    print("--- 도보 네트워크 적재 ---")
    BaseNetworkCollector().save()

    print("--- 자연 데이터 적재 ---")
    NatureCollector().save()

    print("--- 안전 데이터 적재 ---")
    SafetyCollector().save()

    print("--- 러닝 데이터 적재 ---")
    RunningCourseCollector().save()

    print("--- 어린이 시설 적재 ---")
    ChildCollector().save()

    # print("--- 경사로 적재 ---")
    # SlopeCalculator().save()

    # print("--- 랜드마크 적재 ---")
    # asyncio.run(LandmarkCollector().save())
