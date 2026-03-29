import pandas as pd
from sqlalchemy.orm import Session
from src.database.postgresql import engine
from src.entity.poi_network import SafetyPoint, PoiPoint 

def load_layers():
    with Session(engine) as session:
        
        # ==========================================
        # 1. 전국 스마트 가로등 (서울만 필터링)
        # ==========================================
        print("💡 스마트 가로등 데이터 넣는 중...")
        df_lamp = pd.read_csv("src/data/raw/전국스마트가로등표준데이터.csv", encoding='cp949') 
        seoul_lamp = df_lamp[df_lamp['시도명'].str.contains('서울', na=False)]
        
        for _, row in seoul_lamp.iterrows():
            if pd.isna(row['경도']) or pd.isna(row['위도']): continue
            wkt = f"SRID=4326;POINT({row['경도']} {row['위도']})"
            
            # 🛡️ 빈칸(NaN) 방어 코드 적용
            addr = str(row['소재지도로명주소']) if pd.notna(row.get('소재지도로명주소')) else ""
            lamp = SafetyPoint(safety_type="streetlight", address=addr, geom=wkt)
            session.add(lamp)

        # ==========================================
        # 2. CCTV 정보
        # ==========================================
        print("📹 CCTV 데이터 넣는 중...")
        df_cctv = pd.read_excel("src/data/raw/서울시CCTV정보.xlsx") 
        
        for _, row in df_cctv.iterrows():
            if pd.isna(row['WGS84경도']) or pd.isna(row['WGS84위도']): continue
            wkt = f"SRID=4326;POINT({row['WGS84경도']} {row['WGS84위도']})"
            
            # 🛡️ 빈칸(NaN) 방어 코드 적용
            addr = str(row['소재지도로명주소']) if pd.notna(row.get('소재지도로명주소')) else ""
            cctv = SafetyPoint(safety_type="cctv", address=addr, geom=wkt)
            session.add(cctv)

        # ==========================================
        # 3. 서울시 주요 공원
        # ==========================================
        print("🌳 공원 데이터 넣는 중...")
        df_park = pd.read_csv("src/data/raw/서울시 주요 공원현황.csv", encoding='cp949') 
        
        for _, row in df_park.iterrows():
            if pd.isna(row['X좌표(WGS84)']) or pd.isna(row['Y좌표(WGS84)']): continue
            wkt = f"SRID=4326;POINT({row['X좌표(WGS84)']} {row['Y좌표(WGS84)']})"
            
            # 🛡️ 빈칸(NaN) 방어 코드 적용
            name_val = str(row['공원명']) if pd.notna(row.get('공원명')) else ""
            park = PoiPoint(poi_type="park", name=name_val, geom=wkt)
            session.add(park)

        # ==========================================
        # 4. 전국 가로수길 (서울만 필터링)
        # ==========================================
        print("🍃 가로수길 데이터 넣는 중...")
        df_tree = pd.read_csv("src/data/raw/전국가로수길정보표준데이터.csv", encoding='cp949')
        seoul_tree = df_tree[df_tree['제공기관명'].str.contains('서울', na=False)]
        
        for _, row in seoul_tree.iterrows():
            if pd.isna(row['가로수길시작경도']) or pd.isna(row['가로수길시작위도']): continue
            wkt = f"SRID=4326;POINT({row['가로수길시작경도']} {row['가로수길시작위도']})"
            
            # 🛡️ 빈칸(NaN) 방어 코드 적용
            name_val = str(row['가로수길명']) if pd.notna(row.get('가로수길명')) else ""
            tree = PoiPoint(poi_type="tree_road", name=name_val, geom=wkt)
            session.add(tree)

        # 한 방에 저장
        session.commit()
        print("🎉 대성공! 4가지 레이어 데이터가 완벽하게 서울시 맵 위에 얹어졌습니다!")

if __name__ == "__main__":
    load_layers()