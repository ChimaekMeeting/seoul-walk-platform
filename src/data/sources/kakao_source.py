import os

import httpx
from dotenv import load_dotenv

from src.repository.raw.kakao_raw_repository import KakaoRawRepository

load_dotenv()

CATEGORY_CODES: dict[str, str] = {
    "대형마트":       "MT1",
    "편의점":         "CS2",
    "어린이집·유치원": "PS3",
    "학교":           "SC4",
    "주차장":         "PK6",
    "지하철역":       "SW8",
    "은행":           "BK9",
    "문화시설":       "CT1",
    "공공기관":       "PO3",
    "관광명소":       "AT4",
    "음식점":         "FD6",
    "카페":           "CE7",
    "병원":           "HP8",
    "약국":           "PM9",
}

# 서울 격자 중심점 (5x5, ~8km 간격)
_SEOUL_GRID: list[tuple[float, float]] = [
    (37.701, 126.837), (37.701, 126.930), (37.701, 127.023), (37.701, 127.116), (37.701, 127.183),
    (37.641, 126.837), (37.641, 126.930), (37.641, 127.023), (37.641, 127.116), (37.641, 127.183),
    (37.581, 126.837), (37.581, 126.930), (37.581, 127.023), (37.581, 127.116), (37.581, 127.183),
    (37.521, 126.837), (37.521, 126.930), (37.521, 127.023), (37.521, 127.116), (37.521, 127.183),
    (37.461, 126.837), (37.461, 126.930), (37.461, 127.023), (37.461, 127.116), (37.461, 127.183),
]


class KakaoSource:
    TAGS: list[tuple[str, str]] = [
        ("category", code) for code in CATEGORY_CODES.values()
    ]

    def __init__(self):
        self.api_key = os.getenv("KAKAO_API_KEY")
        self.headers = {"Authorization": f"KakaoAK {self.api_key}"}

    def fetch_and_store(self, key: str, value: str) -> None:
        """
        단일 카테고리 데이터를 수집하여 DB에 저장합니다. 이미 저장된 경우 스킵합니다.
        """
        print(f"{value} 데이터를 적재합니다.")
        query_key = f"{key}={value}"
        if KakaoRawRepository.exists(query_key):
            return
        
        # 수집
        items = self._fetch_all(value)

        # 전처리
        items = self.clean(
            items,
            cols=["place_name", "x", "y", "category_name", "address_name", "phone", "place_url"],
            lat_key="y", lon_key="x",
            name_key="place_name", addr_key="address_name",
        )

        # 저장
        KakaoRawRepository.save(items, query_key)

    def store(self) -> None:
        """
        모든 카테고리 데이터를 DB에 저장합니다.
        """
        for key, value in self.TAGS:
            self.fetch_and_store(key, value)

    def get(self, key: str, value: str):
        """
        DB에서 데이터를 조회합니다. 없으면 수집 후 저장합니다.
        """
        query_key = f"{key}={value}"
        if not KakaoRawRepository.exists(query_key):
            self.fetch_and_store(key, value)
        return KakaoRawRepository.get(query_key)

    def clean(
        self,
        items: list[dict],
        cols: list[str],
        lat_key: str = "y",
        lon_key: str = "x",
        name_key: str | None = None,
        addr_key: str | None = None,
    ) -> list[dict]:
        """
        전처리를 수행합니다.
        """
        rename_map = {lat_key: "lat", lon_key: "lon"}
        if name_key:
            rename_map[name_key] = "name"
        if addr_key:
            rename_map[addr_key] = "address"

        result: list[dict] = []
        seen: set[tuple] = set()

        for item in items:
            # 주요 컬럼 추출
            extracted = {k: item.get(k) for k in cols}

            # 결측치 제거
            if any(v in (None, "", "null") for v in extracted.values()):
                continue

            # 경위도 중복 데이터 제거
            coord = (extracted.get(lat_key), extracted.get(lon_key))
            if coord in seen:
                continue
            seen.add(coord)

            # 컬럼명 수정
            result.append({rename_map.get(k, k): v for k, v in extracted.items()})

        return result

    def _fetch_all(self, category_code: str) -> list[dict]:
        """
        서울 격자 기반으로 카테고리 전체 데이터를 수집합니다.
        """
        items: list[dict] = []
        for lat, lon in _SEOUL_GRID:
            items.extend(self._fetch_pages(category_code, lat, lon))
        return items

    def _fetch_pages(self, category_code: str, lat: float, lon: float) -> list[dict]:
        """
        단일 좌표에서 페이지네이션으로 데이터를 수집합니다.
        """
        results = []
        for page in range(1, 4):
            res = httpx.get(
                "https://dapi.kakao.com/v2/local/search/category.json",
                headers=self.headers,
                params={
                    "category_group_code": category_code,
                    "x": lon, "y": lat,
                    "radius": 8000,
                    "page": page, "size": 15,
                },
                timeout=30.0,
            )
            data = res.json()
            docs = data.get("documents", [])
            results.extend(docs)
            if data.get("meta", {}).get("is_end"):
                break
        return results
