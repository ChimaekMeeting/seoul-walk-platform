# -*- coding: utf-8 -*-
"""
안심귀갓길 경로 데이터를 검증 전용 테이블 safe_return_road 로 적재한다.

인수인계 문서 기준 이 데이터는 '검증 전용' 등급이므로 그래프·점수에 넘기지 않는다.
사용: poetry run python analysis/load_safe_return_road.py
"""
import sys
from pathlib import Path

# analysis/ 안에서 실행해도 저장소 루트의 src 패키지를 찾도록 경로를 추가한다.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import geopandas as gpd
import pandas as pd

from src.entity.base import engine

SRC = ROOT / "src/data/raw/안심귀갓길 경로 데이터_수정.shp"

RENAME = {
    "길이":        "length_src",
    "시군구명":     "gu",
    "읍면동명":     "dong",
    "안심벨":      "bell_cnt",
    "CCTV":       "cctv_cnt",
    "보안등":      "light_cnt",
    "112 위치신":  "police_cnt",
    "안심귀갓_4":  "name",
    "조성년월":     "built_year",
    "세부위치":     "location",
}


def main() -> None:
    gdf = gpd.read_file(str(SRC), encoding="euc-kr")
    gdf = gdf.rename(columns=RENAME)[list(RENAME.values()) + ["geometry"]]

    # 원본 개수 열은 문자열·공백이 섞여 있어 숫자로 변환한다(변환 불가는 결측 처리).
    for col in ("length_src", "bell_cnt", "cctv_cnt", "light_cnt", "police_cnt"):
        gdf[col] = pd.to_numeric(gdf[col], errors="coerce")

    gdf["gu"] = gdf["gu"].str.replace("서울특별시 ", "", regex=False)

    if gdf.crs is None:
        raise ValueError("좌표계 정보가 없습니다.")
    gdf = gdf.to_crs("EPSG:4326")
    gdf = gdf.rename_geometry("geom")

    gdf.to_postgis("safe_return_road", engine, if_exists="replace", index=False)
    print(f"safe_return_road 적재 완료: {len(gdf)}건")
    print(gdf[["gu", "cctv_cnt", "light_cnt"]].describe().to_string())


if __name__ == "__main__":
    main()
