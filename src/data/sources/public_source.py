import os

import httpx
from dotenv import load_dotenv

from src.repository.raw.public_raw_repository import PublicRawRepository

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
        print(f"{value} 데이터를 적재합니다.")
        query_key = f"{key}={value}"
        if PublicRawRepository.exists(query_key):
            return
        
        # 수집
        items, lat_key, lon_key, name_key, addr_key, city_key = self._fetch_all(value)

        # 전처리
        items = self.clean(
            items,
            lat_key=lat_key, lon_key=lon_key,
            name_key=name_key, addr_key=addr_key,
            city_key=city_key,
        )

        # 저장
        PublicRawRepository.save(items, query_key)

    def store(self) -> None:
        """
        모든 데이터셋을 DB에 저장합니다.
        """
        for key, value in self.TAGS:
            self.fetch_and_store(key, value)

    def get(self, key: str, value: str):
        """
        DB에서 데이터를 조회합니다. 없으면 수집 후 저장합니다.
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
        name_key: str | None = None,
        addr_key: str | None = None,
        city_key: str | None = None,
        city_value: str = "서울",
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
            # 결측치 제거
            if any(v in (None, "", "null") for v in item.values()):
                continue

            # 서울 필터링
            if city_key and city_value not in str(item.get(city_key, "")):
                continue

            # 경위도 중복 데이터 제거
            coord = (item.get(lat_key), item.get(lon_key))
            if coord in seen:
                continue
            seen.add(coord)

            # 컬럼명 수정
            result.append({rename_map.get(k, k): v for k, v in item.items()})

        return result

    def _fetch_all(self, value: str):
        """
        value에 따라 수집 메서드를 디스패치합니다.
        Returns: (items, lat_key, lon_key, name_key, addr_key, city_key)
        """
        dispatch = {
            "play_facility": self._fetch_play_facility,
        }
        if value not in dispatch:
            raise NotImplementedError(f"'{value}' 데이터셋 fetch 미구현")
        return dispatch[value]()

    def _fetch_play_facility(self):
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

        #                 lat          lon         name       addr       city
        return items, "latCrtsVl", "lotCrtsVl", "pfctNm", "ronaAddr", "ronaAddr"
