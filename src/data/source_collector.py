from src.data.sources.osm_source import OSMSource
from src.data.sources.kakao_source import KakaoSource
from src.data.sources.public_source import PublicSource
from src.data.sources.csv_source import CSVSource

if __name__ == "__main__":
    # raw 테이블(osm_raw, kakao_raw, public_raw, csv_raw)을 미리 채웁니다.
    # 이미 저장된 데이터는 자동으로 스킵됩니다.

    # 실행 순서:
    # 1. python -m src.main                    # 테이블 생성
    # 2. python -m src.data.source_collector   # raw 데이터 적재  ← 여기
    # 3. python -m src.data.data_collector     # 도메인 데이터 적재

    print("--- OSM raw 적재 ---")
    OSMSource().store()

    print("--- Kakao raw 적재 ---")
    KakaoSource().store()

    print("--- 공공데이터 raw 적재 ---")
    PublicSource().store()

    print("--- CSV/XLSX raw 적재 ---")
    CSVSource().store()

    print("✅ 모든 raw 데이터 적재 완료")
