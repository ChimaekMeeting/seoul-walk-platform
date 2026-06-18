import os

import httpx
from dotenv import load_dotenv

from src.repository.public_raw_repository import PublicRawRepository

load_dotenv()


class PublicSource:
    TAGS: list[tuple[str, str]] = [
        ("type", "play_facility"),
    ]

    def __init__(self):
        self.api_key = os.getenv("PUBLIC_DATA_API_KEY")


    def fetch_and_store(self, key: str, value: str) -> None:
        """
        단일 데이터셋을 수집하여 DB에 저장합니다. 이미 저장된 경우 스킵합니다.
        """
        query_key = f"{key}={value}"
        if PublicRawRepository.exists(query_key):
            return

        items, lat_key, lon_key, name_key, city_key = self._fetch_all(value)
        items = self.clean(items, lat_key=lat_key, lon_key=lon_key, city_key=city_key)
        PublicRawRepository.save_items(items, query_key,
                                       lat_key=lat_key, lon_key=lon_key, name_key=name_key)

    def store(self) -> None:
        """
        TAGS의 모든 데이터셋을 DB에 저장합니다.
        """
        for key, value in self.TAGS:
            self.fetch_and_store(key, value)

    def get(self, key: str, value: str):
        """
        DB에서 데이터를 조회합니다. DB에 없으면 수집 후 저장합니다.
        """
        query_key = f"{key}={value}"
        if not PublicRawRepository.exists(query_key):
            self.fetch_and_store(key, value)
        return PublicRawRepository.get(query_key)

    def clean(
        self,
        items: list[dict],
        lat_key: str,
        lon_key: str,
        city_key: str | None = None,
        city_value: str = "서울",
    ) -> list[dict]:
        """
        기본 전처리를 수행합니다.
        """
        result: list[dict] = []
        seen: set[tuple] = set()

        for item in items:
            if any(v in (None, "", "null") for v in item.values()):
                continue

            if city_key and city_value not in str(item.get(city_key, "")):
                continue

            coord = (item.get(lat_key), item.get(lon_key))
            if coord in seen:
                continue
            seen.add(coord)

            result.append(item)

        return result

    def _fetch_all(self, value: str) -> tuple[list[dict], str, str, str | None, str | None]:
        """
        데이터셋 value에 따라 수집 메서드를 디스패치합니다.
        """
        dispatch = {
            "play_facility": self._fetch_play_facility,
        }
        if value not in dispatch:
            raise NotImplementedError(f"'{value}' 데이터셋 fetch 미구현")
        return dispatch[value]()

    def _fetch_play_facility(self) -> tuple[list[dict], str, str, str, str]:
        """
        어린이놀이시설 데이터를 수집합니다. 운영 중인 시설만 포함합니다.
        """
        url = "https://apis.data.go.kr/1741000/pfc3/getPfctInfo3"
        items = []

        for page in range(1, 88):
            res = httpx.get(
                url,
                params={
                    "serviceKey": self.api_key,
                    "recordCountPerPage": 1000,
                    "pageIndex": page,
                },
                timeout=30.0,
            )
            rows = res.json().get("response", {}).get("body", {}).get("items", [])
            if not rows:
                break

            for row in rows:
                if row.get("operYnCdNm") != "운영":
                    continue
                items.append({
                    "pfctNm":    row.get("pfctNm"),
                    "ronaAddr":  row.get("ronaAddr"),
                    "latCrtsVl": row.get("latCrtsVl"),
                    "lotCrtsVl": row.get("lotCrtsVl"),
                })

        return items, "latCrtsVl", "lotCrtsVl", "pfctNm", "ronaAddr"
