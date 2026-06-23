import pandas as pd

from src.infrastructure.external.client.kakao_client import KakaoClient
from src.repository.layer.safety_repository import SafetyRepository
from src.repository.layer.nature_repository import NatureRepository
from src.repository.layer.landmark_repository import LandmarkRepository
from src.repository.layer.child_repository import ChildRepository
from src.repository.layer.running_repository import RunningRepository
from src.repository.network.edge_repository import EdgeRepository


class MapService:

    def __init__(self, kakao_client: KakaoClient):
        """
        MapService 초기화
        """
        self.kakao_client = kakao_client

    async def fetch_kakao_facilities(self, lat, lon, category_code=None, keyword=None, radius=2000) -> list[dict]:
        """
        카카오 API로 시설물 목록을 조회합니다.
        """
        all_places = []
        for page in range(1, 4):
            data = await self.kakao_client.search_places(lat, lon, page, radius, category_code=category_code, keyword=keyword)
            if not data:
                break
            all_places.extend(data.documents)
            if data.meta.is_end:
                break
        return all_places

    def fetch_safety_points(self, lat, lon, radius_m=2000) -> pd.DataFrame:
        """
        DB에서 주변 안전 시설물 포인트 전체를 조회합니다.
        """
        return SafetyRepository.get(lat, lon, radius_m)

    def fetch_nature_points(self, lat, lon, radius_m=2000) -> pd.DataFrame:
        """
        DB에서 주변 녹지 포인트 전체를 조회합니다.
        """
        return NatureRepository.get(lat, lon, radius_m)

    def fetch_landmark_points(self, lat, lon, radius_m=2000) -> pd.DataFrame:
        """
        DB에서 주변 랜드마크 포인트 전체를 조회합니다.
        """
        return LandmarkRepository.get(lat, lon, radius_m)

    def fetch_child_points(self, lat, lon, radius_m=2000) -> pd.DataFrame:
        """
        DB에서 주변 어린이 시설 포인트 전체를 조회합니다.
        """
        return ChildRepository.get(lat, lon, radius_m)

    def fetch_running_points(self, lat, lon, radius_m=2000) -> pd.DataFrame:
        """
        DB에서 주변 러닝 코스 포인트 전체를 조회합니다.
        """
        return RunningRepository.get(lat, lon, radius_m)

    def fetch_db_lines(self, lat, lon, radius_m=2000) -> pd.DataFrame:
        """
        DB에서 주변 도로 라인 데이터를 조회합니다.
        """
        return EdgeRepository.fetch_nearby_lines(lat, lon, radius_m)
