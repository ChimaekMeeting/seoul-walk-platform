"""
frontend/streamlit_prototype/components/layer/map_layer.py

지도 레이어 데이터를 API를 통해 조회하고 DataFrame으로 변환하는 컴포넌트
카카오 시설, DB 포인트, DB 엣지 3가지 레이어를 제공
"""
import pandas as pd
import streamlit as st

from frontend.streamlit_prototype.api.map_router import MapRouter


class MapLayer:

    def __init__(self):
        self._router = MapRouter()

    @st.cache_data(ttl=3600)
    def fetch_kakao_facilities_df(
        _self,
        lat: float,
        lon: float,
        category_code: str | None = None,
        keyword: str | None = None,
        radius: int = 2000,
    ) -> pd.DataFrame:
        """
        input : lat, lon, category_code, keyword, radius
        output: DataFrame (name, lon, lat, address)

        GET /api/map/facilities 호출 후 DataFrame으로 변환
        """
        data = _self._router.get_facilities(lat, lon, category_code=category_code, keyword=keyword, radius=radius)
        return pd.DataFrame(data) if data else pd.DataFrame()

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
        input : lat, lon, table_name, type_col, type_val, radius_m
        output: DataFrame (lat, lon)

        GET /api/map/points 호출 후 DataFrame으로 변환
        """
        data = _self._router.get_points(lat, lon, table_name, type_col, type_val, radius_m)
        return pd.DataFrame(data) if data else pd.DataFrame()

    @st.cache_data(ttl=3600)
    def fetch_local_db_lines_optimized(
        _self,
        lat: float,
        lon: float,
        radius_m: int = 2000,
    ) -> pd.DataFrame:
        """
        input : lat, lon, radius_m
        output: DataFrame (path, link_id)

        GET /api/map/edges 호출 후 DataFrame으로 변환
        GeoJSON 파싱은 서버에서 처리해 path([[lon, lat], ...])로 반환됨
        """
        data = _self._router.get_edges(lat, lon, radius_m)
        return pd.DataFrame(data) if data else pd.DataFrame()
