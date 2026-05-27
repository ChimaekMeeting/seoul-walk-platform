import json
import pandas as pd
from sqlalchemy import text

from src.entity.base import engine
from src.infrastructure.external.client.kakao_client import KakaoClient

kakao_client = KakaoClient()


async def fetch_kakao_facilities(lat, lon, category_code=None, keyword=None, radius=2000) -> list[dict]:
    """카카오 API로 시설물 목록을 조회합니다."""
    all_places = []
    for page in range(1, 4):
        data = await kakao_client.search_places(lat, lon, page, radius, category_code=category_code, keyword=keyword)
        if not data:
            break
        all_places.extend(data.get("documents", []))
        if data.get("meta", {}).get("is_end"):
            break
    return all_places


def fetch_db_points(lat, lon, table_name, type_col=None, type_val=None, radius_m=2000) -> pd.DataFrame:
    """PostGIS를 사용하여 포인트 데이터를 조회합니다."""
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
        print(f"DB 포인트 조회 실패 ({table_name}): {e}")
        return pd.DataFrame()


def fetch_db_lines(lat, lon, radius_m=2000) -> pd.DataFrame:
    """도보 네트워크 라인 데이터를 조회합니다. (geometry 컬럼 포함)"""
    query_str = """
        SELECT ST_AsGeoJSON(ST_Simplify(geom, 0.00005)) as geometry, link_id
        FROM walk_edges
        WHERE ST_DWithin(
            geom::geography,
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
            :radius
        )
    """
    try:
        with engine.connect() as conn:
            return pd.read_sql(
                text(query_str),
                conn,
                params={"lat": lat, "lon": lon, "radius": radius_m},
            )
    except Exception as e:
        print(f"DB 라인 조회 실패: {e}")
        return pd.DataFrame()
