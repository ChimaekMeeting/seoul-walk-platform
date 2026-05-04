import pandas as pd
from sqlalchemy import create_engine
from src.database.postgresql import engine
from sqlalchemy.sql import text

def fast_load_walk_network(csv_path: str):
    print(f"🚀 [{csv_path}] 고속 벌크 적재를 시작합니다...")

    # 1. CSV 데이터 로드 (필요한 컬럼만 선택적으로 읽기)
    try:
        df = pd.read_csv(csv_path, encoding='cp949')
    except UnicodeDecodeError:
        df = pd.read_csv(csv_path, encoding='utf-8')

    # 2. 링크(LINK) 데이터만 추출 및 전처리
    edges_df = df[df['노드링크 유형'] == 'LINK'].copy()

    # PostGIS가 인식 가능한 WKT 형식으로 변환
    edges_df['geom'] = edges_df['링크 WKT'].apply(lambda x: f"SRID=4326;{x}")

    # DB 스키마에 맞게 컬럼명 매핑
    processed_df = edges_df[[
        '링크 ID', '시작노드 ID', '종료노드 ID', '링크 길이', '링크 유형 코드', 'geom'
    ]].rename(columns={
        '링크 ID': 'link_id',
        '시작노드 ID': 'start_node',
        '종료노드 ID': 'end_node',
        '링크 길이': 'length_m',
        '링크 유형 코드': 'road_type'
    })

    # 3. DB 적재 (기존 데이터 삭제 후 새로 삽입하는 방식 추천)
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE walk_edges RESTART IDENTITY CASCADE;"))
        processed_df.to_sql(
            'walk_edges',
            con=conn,
            if_exists='append',
            index=False,
            method='multi',
            chunksize=10000
        )

    print(f"🎉 성공! 총 {len(processed_df)}개의 도보 네트워크가 적재되었습니다.")

if __name__ == "__main__":
    CSV_FILE_PATH = "src/data/raw/서울시 자치구별 도보 네트워크 공간정보.csv"
    fast_load_walk_network(CSV_FILE_PATH)