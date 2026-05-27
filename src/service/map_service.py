import asyncio
import pandas as pd
import streamlit as st
import json
from sqlalchemy import text
from src.entity.base import engine  # 프로젝트 설정에 따른 DB 엔진 임포트
from src.infrastructure.external.client.kakao_client import KakaoClient

kakao_client = KakaoClient()

# --- 1. 카카오 API 시설물 조회 (기존 기능 유지) ---
@st.cache_data(ttl=3600)
async def fetch_kakao_facilities_df(lat, lon, category_code=None, keyword=None, radius=2000):
    """
    카카오 API 결과물을 지도에 표시하기 좋은 데이터프레임으로 변환합니다.
    """
    all_places = []
    for page in range(1, 4):  # 최대 45개 수집
        data = await kakao_client.search_places(lat, lon, page, radius, category_code=category_code, keyword=keyword)
        if not data:
            break
        places = data.get("documents", [])
        all_places.extend(places)
        if data.get("meta", {}).get("is_end"):
            break

    if not all_places:
        return pd.DataFrame()

    return pd.DataFrame([
        {
            "name": p["place_name"],
            "lon": float(p["x"]),
            "lat": float(p["y"]),
            "address": p["address_name"],
        }
        for p in all_places
    ])

# --- 2. 로컬 DB 포인트 조회 (CCTV, 가로등 등) ---
@st.cache_data(ttl=3600)
def fetch_local_db_points(lat, lon, table_name, type_col=None, type_val=None, radius_m=2000):
    """
    PostGIS를 사용하여 포인트 데이터를 조회합니다.
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
    if type_col and type_val:
        query_str += f" AND {type_col} = :type_val"

    try:
        with engine.connect() as conn:
            params = {"lat": lat, "lon": lon, "radius": radius_m, "type_val": type_val}
            return pd.read_sql(text(query_str), conn, params=params)
    except Exception as e:
        print(f"❌ DB 포인트 조회 실패 ({table_name}): {e}")
        return pd.DataFrame()

# --- 3. [성능 최적화] 로컬 DB 라인 조회 (도보 네트워크) ---
@st.cache_data(ttl=3600)
def fetch_local_db_lines_optimized(lat, lon, radius_m=2000):
    """
    ST_Simplify를 사용하여 데이터를 경량화하고,
    PyDeck의 PathLayer 포맷으로 즉시 변환합니다.
    """
    # [핵심] ST_Simplify(geom, 0.00005): 약 5m 단위 단순화로 96MB 데이터를 획기적으로 줄임
    query_str = """
                SELECT ST_AsGeoJSON(ST_Simplify(geom, 0.00005)) as geometry, link_id
                FROM walk_edges
                WHERE ST_DWithin(
                              geom::geography,
                              ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                              :radius
                      ) \
                """
    try:
        with engine.connect() as conn:
            df = pd.read_sql(
                text(query_str),
                conn,
                params={"lat": lat, "lon": lon, "radius": radius_m},
            )

        if not df.empty:
            # GeoJSON 문자열을 PyDeck용 좌표 리스트(path)로 변환
            df["path"] = df["geometry"].apply(lambda x: json.loads(x)["coordinates"])
            return df[["path", "link_id"]]

        return pd.DataFrame()
    except Exception as e:
        print(f"❌ DB 라인 조회 실패: {e}")
        return pd.DataFrame()