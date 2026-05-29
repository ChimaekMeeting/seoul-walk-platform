import json

import pandas as pd
import streamlit as st

from src.service.route.map_service import fetch_kakao_facilities, fetch_db_points, fetch_db_lines


class MapLayer:

    @st.cache_data(ttl=3600)
    async def fetch_kakao_facilities_df(
        _self,
        lat: float,
        lon: float,
        category_code: str | None = None,
        keyword: str | None = None,
        radius: int = 2000,
    ) -> pd.DataFrame:
        """
        카카오 API 결과물을 지도에 표시하기 좋은 데이터프레임으로 변환합니다.
        """
        all_places = await fetch_kakao_facilities(
            lat, lon, category_code=category_code, keyword=keyword, radius=radius
        )
        if not all_places:
            return pd.DataFrame()
        return pd.DataFrame([
            {"name": p["place_name"], "lon": float(p["x"]), "lat": float(p["y"]), "address": p["address_name"]}
            for p in all_places
        ])

    @st.cache_data(ttl=3600)
    def fetch_local_db_points(
        _self,
        lat: float,
        lon: float,
        table_name: str,
        type_col: str | None = None,
        type_val: str | None = None,
        radius_m: int = 2000,
    ) -> pd.DataFrame:
        """
        PostGIS 포인트 데이터를 캐싱하여 반환합니다.
        """
        return fetch_db_points(lat, lon, table_name, type_col, type_val, radius_m)

    @st.cache_data(ttl=3600)
    def fetch_local_db_lines_optimized(
        _self,
        lat: float,
        lon: float,
        radius_m: int = 2000,
    ) -> pd.DataFrame:
        """
        도보 네트워크를 PyDeck PathLayer 포맷(path 컬럼)으로 반환합니다.
        """
        df = fetch_db_lines(lat, lon, radius_m)
        if df.empty:
            return pd.DataFrame()
        df["path"] = df["geometry"].apply(lambda x: json.loads(x)["coordinates"])
        return df[["path", "link_id"]]
