import json

import pandas as pd
import streamlit as st

from src.infrastructure.external.client.kakao_client import KakaoClient
from src.service.route.map_service import MapService
from src.repository.layer.map_repository import MapRepository
from src.repository.network.edge_repository import EdgeRepository


class MapLayer:

    def __init__(self):
        self._map_service = MapService(KakaoClient())

    @st.cache_data(ttl=3600)
    async def fetch_kakao_facilities_df(
        _self,
        lat: float,
        lon: float,
        category_code: str | None = None,
        keyword: str | None = None,
        radius: int = 2000,
    ) -> pd.DataFrame:
        all_places = await _self._map_service.fetch_kakao_facilities(
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
        return MapRepository.fetch_nearby_points(lat, lon, table_name, type_col, type_val, radius_m)

    @st.cache_data(ttl=3600)
    def fetch_local_db_lines_optimized(
        _self,
        lat: float,
        lon: float,
        radius_m: int = 2000,
    ) -> pd.DataFrame:
        df = EdgeRepository.fetch_nearby_lines(lat, lon, radius_m)
        if df.empty:
            return pd.DataFrame()
        df["path"] = df["geometry"].apply(lambda x: json.loads(x)["coordinates"])
        return df[["path", "link_id"]]
