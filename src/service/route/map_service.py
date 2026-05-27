import pandas as pd

from src.infrastructure.external.client.kakao_client import KakaoClient
from src.repository.layer.map_repository import MapRepository
from src.repository.network.edge_repository import EdgeRepository

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
    return MapRepository.fetch_nearby_points(lat, lon, table_name, type_col, type_val, radius_m)


def fetch_db_lines(lat, lon, radius_m=2000) -> pd.DataFrame:
    return EdgeRepository.fetch_nearby_lines(lat, lon, radius_m)
