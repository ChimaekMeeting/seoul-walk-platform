import pandas as pd
import streamlit as st
import json
from sqlalchemy import text
from src.entity.base import engine  # DB 연결 엔진
from src.api.kakao_api import get_kakao_places_page


@st.cache_data(ttl=3600)
def fetch_kakao_facilities_df(lat, lon, category_code=None, keyword=None, radius=2000):
    """
    카카오 API 결과물을 지도에 표시하기 좋은 데이터프레임으로 변환합니다.
    """
    all_places = []
    for page in range(1, 4):  # 최대 45개 수집
        data = get_kakao_places_page(lat, lon, page, radius, category_code, keyword)
        if not data:
            break
        places = data.get("documents", [])
        all_places.extend(places)
        if data.get("meta", {}).get("is_end"):
            break

    if not all_places:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "name": p["place_name"],
                "lon": float(p["x"]),
                "lat": float(p["y"]),
                "address": p["address_name"],
            }
            for p in all_places
        ]
    )


@st.cache_data(ttl=3600)
def fetch_local_db_points(
    lat, lon, table_name, type_col=None, type_val=None, radius_m=2000
):
    """
    PostGIS 공간 쿼리를 사용하여 로컬 DB의 '점(Point)' 데이터(CCTV, 가로등 등)를 반경 검색합니다.
    """
    query_str = f"""
        SELECT ST_Y(geom) as lat, ST_X(geom) as lon
        FROM {table_name}
        WHERE ST_DWithin(
            geom::geography, 
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, 
            :radius
        )
    """
    # 특정 타입 필터링 (예: safety_type = 'cctv')
    if type_col and type_val:
        query_str += f" AND {type_col} = :type_val"

    try:
        with engine.connect() as conn:
            params = {"lat": lat, "lon": lon, "radius": radius_m, "type_val": type_val}
            return pd.read_sql(text(query_str), conn, params=params)
    except Exception as e:
        print(f"❌ DB 포인트 조회 실패 ({table_name}): {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def fetch_local_db_lines(lat, lon, radius_m=2000):
    """
    PostGIS 공간 쿼리를 사용하여 로컬 DB의 '선(Line)' 데이터(도보 네트워크)를 반경 검색합니다.
    """
    query_str = """
        SELECT ST_AsGeoJSON(geom) as geometry
        FROM walk_edges
        WHERE ST_DWithin(
            geom::geography, 
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, 
            :radius
        )
    """
    try:
        with engine.connect() as conn:
            df = pd.read_sql(
                text(query_str),
                conn,
                params={"lat": lat, "lon": lon, "radius": radius_m},
            )
        if not df.empty:
            df["geometry"] = df["geometry"].apply(
                json.loads
            )  # GeoJSON 문자열을 객체로 변환
        return df
    except Exception as e:
        print(f"❌ DB 라인 조회 실패: {e}")
        return pd.DataFrame()
