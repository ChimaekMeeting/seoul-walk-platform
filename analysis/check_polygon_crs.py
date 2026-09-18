# analysis/check_polygon_crs.py 로 저장
import re
import json
from shapely.geometry import shape
import pyproj

def parse_polygon_str(s):
    s = re.sub(r'\b(type|coordinates)\s*:', r'"\1":', s)
    s = re.sub(r'"type":\s*([A-Za-z]+)', r'"type": "\1"', s)
    return json.loads(s)

import pandas as pd
df = pd.read_csv("src/data/raw/전국교통사고다발지역표준데이터.csv", encoding="cp949")
seoul = df[df["사고다발지역시도시군구"].str.contains("서울", na=False)].copy()
pedestrian_types = ["보행노인", "보행어린이", "스쿨존어린이"]
seoul_ped = seoul[seoul["사고유형구분"].isin(pedestrian_types)].copy()

row = seoul_ped.iloc[0]
geo_dict = parse_polygon_str(row["사고다발지역폴리곤정보"])
poly = shape(geo_dict)

cx, cy = poly.centroid.x, poly.centroid.y
orig_lat, orig_lon = row["위도"], row["경도"]

print("중심점(투영좌표):", cx, cy)
print("원본 위도:", orig_lat, "원본 경도:", orig_lon)
print()

for epsg in [5179, 5181, 5186]:
    try:
        transformer = pyproj.Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
        lon, lat = transformer.transform(cx, cy)
        print(f"EPSG:{epsg} 역변환 -> 위도 {lat:.6f}, 경도 {lon:.6f}")
    except Exception as e:
        print(f"EPSG:{epsg} 실패:", e)