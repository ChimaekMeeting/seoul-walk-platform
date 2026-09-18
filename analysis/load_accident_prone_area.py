import re
import json
import pandas as pd
import geopandas as gpd
from shapely.geometry import shape
from src.entity.base import engine

def parse_polygon_str(s):
    s = re.sub(r'\b(type|coordinates)\s*:', r'"\1":', s)
    s = re.sub(r'"type":\s*([A-Za-z]+)', r'"type": "\1"', s)
    return json.loads(s)

df = pd.read_csv("src/data/raw/전국교통사고다발지역표준데이터.csv", encoding="cp949")
seoul = df[df["사고다발지역시도시군구"].str.contains("서울", na=False)].copy()

# 보행 관련 유형만 (자전거 제외)
pedestrian_types = ["보행노인", "보행어린이", "스쿨존어린이"]
seoul_ped = seoul[seoul["사고유형구분"].isin(pedestrian_types)].copy()

# 최근 3개년 (TMACS 기준)
seoul_ped = seoul_ped[seoul_ped["사고연도"] >= 2022].copy()

# 사망자 발생 플래그
seoul_ped["has_death"] = (seoul_ped["사망자수"] > 0)

# 폴리곤 파싱 -> geometry (EPSG:5179)
seoul_ped["geom"] = seoul_ped["사고다발지역폴리곤정보"].apply(
    lambda s: shape(parse_polygon_str(s))
)

gdf = gpd.GeoDataFrame(seoul_ped, geometry="geom", crs="EPSG:5179")

# DB 저장 기준 좌표계는 프로젝트 다른 테이블과 맞춰 WGS84로 변환
gdf = gdf.to_crs("EPSG:4326")

gdf.to_postgis("accident_prone_area", engine, if_exists="replace", index=False)