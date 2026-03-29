import pandas as pd
from shapely.wkt import loads
from sqlalchemy.orm import Session
from src.database.postgresql import engine
from src.entity.walk_network import WalkNode, WalkEdge

def load_walk_network_from_csv(csv_path: str):
    print(f"🚀 [{csv_path}] 파일에서 도보 네트워크 적재를 시작합니다...")
    
    # 1. CSV 파일 읽기
    try:
        df = pd.read_csv(csv_path, encoding='cp949')
    except UnicodeDecodeError:
        df = pd.read_csv(csv_path, encoding='utf-8')

    # 2. 노드(NODE) 데이터 필터링 (컬럼명 수정됨)
    nodes_df = df[df['노드링크 유형'] == 'NODE'].copy()
    print(f"👉 추출된 노드 개수: {len(nodes_df)}개")

    # 3. 링크(LINK) 데이터 필터링 (컬럼명 수정됨)
    edges_df = df[df['노드링크 유형'] == 'LINK'].copy()
    print(f"👉 추출된 링크 개수: {len(edges_df)}개")

    with Session(engine) as session:
        # --- 4. 노드 데이터 DB 적재 ---
        for _, row in nodes_df.iterrows():
            if pd.isna(row['노드 WKT']): continue
            
            geom_wkt = f"SRID=4326;{row['노드 WKT']}"
            
            node = WalkNode(
                node_id=int(row['노드 ID']),
                node_type=str(row['노드 유형 코드']),
                is_underground=bool(row.get('지하철네트워크', 0)), 
                is_overpass=bool(row.get('육교', 0)),
                geom=geom_wkt
            )
            session.merge(node)
        
        print("✅ 노드 데이터 메모리 적재 완료. 이제 링크를 넣습니다...")

        # --- 5. 링크 데이터 DB 적재 ---
        for _, row in edges_df.iterrows():
            if pd.isna(row['링크 WKT']): continue
            
            geom_wkt = f"SRID=4326;{row['링크 WKT']}"
            
            path_type = "park" if row.get('공원,녹지') == 1 else "sidewalk"

            edge = WalkEdge(
                link_id=int(row['링크 ID']),
                start_node=int(row['시작노드 ID']),
                end_node=int(row['종료노드 ID']),
                length_m=float(row['링크 길이']),
                road_type=str(row['링크 유형 코드']),
                path_type=path_type,
                geom=geom_wkt
            )
            session.merge(edge)
        
        session.commit()
        print("🎉 대성공! 노드와 링크가 데이터베이스에 완벽하게 저장되었습니다!")

if __name__ == "__main__":
    # 파일 이름에 띄어쓰기가 있어도 이렇게 따옴표로 묶으면 잘 읽습니다!
    CSV_FILE_PATH = "src/data/raw/서울시 자치구별 도보 네트워크 공간정보.csv"
    load_walk_network_from_csv(CSV_FILE_PATH)