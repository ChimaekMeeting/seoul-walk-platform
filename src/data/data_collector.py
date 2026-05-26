import asyncio

from src.data.collectors.base_network import BaseNetworkCollector
from src.data.collectors.nature_collector import NatureCollector
from src.data.collectors.safety_collector import SafetyCollector
from src.data.collectors.landmark_collector import LandmarkCollector
from src.data.collectors.running_course_collector import collect_running_courses

if __name__ == "__main__":
    # 이미 DB에 저장된 데이터 관련 collector는 주석 처리해주세요!
    # 실행 방법:
    # 1. python -m src.main                 # 테이블 생성
    # 2. python -m src.data.data_collector  # 데이터 적재

    base_collector = BaseNetworkCollector()
    nature_collector = NatureCollector()
    safety_collector = SafetyCollector()
    landmark_collector = LandmarkCollector()

    print("--- 도보 데이터 적재 ---")
    base_collector.save()

    print("--- 자연 데이터 적재 ---")
    nature_collector.save()

    print("--- 안전 데이터 적재 ---")
    safety_collector.save()

    # print("--- 랜드마크 데이터 적재 ---")
    # asyncio.run(landmark_collector.save())

    # print("--- 러닝 데이터 적재 ---")
    # collect_running_courses()