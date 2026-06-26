import logging
import os

import httpx
from dotenv import load_dotenv

from src.repository.raw.public_raw_repository import PublicRawRepository

load_dotenv()

logger = logging.getLogger(__name__)


class PublicSource:
    TAGS: list[tuple[str, str]] = [
        ("type", "play_facility"),
        ("type", "landmark"),
        ("type", "accident_zone"),
        ("type", "outdoor_exercise"),
    ]

    def __init__(self):
        self.api_key = os.getenv("PUBLIC_DATA_API_KEY")

    def fetch_and_store(self, key: str, value: str) -> None:
        query_key = f"{key}={value}"
        if PublicRawRepository.exists(query_key):
            logger.debug("%s 이미 적재됨, 스킵", query_key)
            return

        logger.info("공공데이터 %s 수집 시작", value)
        # 수집
        items, lat_key, lon_key, name_key, addr_key, city_key = self._fetch_all(value)
        logger.debug("%s 원본 %d건 수집", value, len(items))

        # 전처리
        items = self.clean(
            items,
            lat_key=lat_key, lon_key=lon_key,
            name_key=name_key, addr_key=addr_key,
            city_key=city_key,
        )
        logger.debug("%s 전처리 후 %d건", value, len(items))

        # 저장
        PublicRawRepository.save(items, query_key)
        logger.info("%s 적재 완료: %d건", value, len(items))

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
            "landmark": self._fetch_landmark,
            "accident_zone":    self._fetch_accident_zone,
            "outdoor_exercise": self._fetch_outdoor_exercise,
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
                    "_type": "json",
                },
                timeout=30.0,
            )
            if res.status_code != 200:
                logger.warning("어린이놀이시설 page %d HTTP %d, 건너뜀", page, res.status_code)
                break
            try:
                rows = res.json().get("response", {}).get("body", {}).get("items", [])
            except Exception:
                logger.warning("어린이놀이시설 page %d JSON 파싱 실패, 건너뜀", page)
                break
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

    def _fetch_landmark(self):
        url = "https://apis.data.go.kr/B551011/KorService2/areaBasedList2"
        items = []

        for content_type_id in [12, 14]:  # 관광지, 문화시설
            page = 1
            while True:
                res = httpx.get(url, params={
                    "serviceKey":    self.api_key,
                    "MobileOS":      "ETC",
                    "MobileApp":     "SeoulWalk",
                    "_type":         "json",
                    "areaCode":      1,
                    "contentTypeId": content_type_id,
                    "numOfRows":     100,
                    "pageNo":        page,
                    "arrange":       "A",
                }, timeout=30.0)
                logger.debug("TourAPI contentTypeId=%d page=%d → HTTP %d", content_type_id, page, res.status_code)
                if res.status_code != 200:
                    logger.warning("TourAPI contentTypeId=%d page=%d HTTP %d, 건너뜀", content_type_id, page, res.status_code)
                    break

                body = res.json().get("response", {}).get("body", {})
                item_list = body.get("items", {}).get("item", [])
                if isinstance(item_list, dict):
                    item_list = [item_list]
                if not item_list:
                    break

                for item in item_list:
                    if not item.get("mapx") or not item.get("mapy"):
                        continue
                    items.append({
                        "title": item.get("title"),
                        "addr1": item.get("addr1"),
                        "mapx":  item.get("mapx"),
                        "mapy":  item.get("mapy"),
                    })

                if page * 100 >= body.get("totalCount", 0):
                    break
                page += 1

        return items, "mapy", "mapx", "title", "addr1", "addr1"
    
    def _fetch_outdoor_exercise(self):
        """전국실외운동기구설치정보 표준데이터 (JSON)."""
        url = "https://api.data.go.kr/openapi/tn_pubr_public_outdoor_exercise_eqmt_api"
        items = []
        page = 1
        while True:
            res = httpx.get(url, params={
                "serviceKey": self.api_key,
                "pageNo":     page,
                "numOfRows":  1000,
                "type":       "json",
            }, timeout=30.0)
            body = res.json().get("response", {}).get("body", {})
            rows = body.get("items", [])
            if not rows:
                break
            for row in rows:
                items.append({
                    "instlPlcNm":    row.get("instlPlcNm"),
                    "lctnLotnoAddr": row.get("lctnLotnoAddr") or row.get("lctnRoadNmAddr"),
                    "lat":           row.get("lat"),
                    "lot":           row.get("lot"),
                    "ctpvNm":        row.get("ctpvNm"),
                })
            total = body.get("totalCount", 0)
            if page * 1000 >= int(total or 0):
                break
            page += 1
        return items, "lat", "lot", "instlPlcNm", "lctnLotnoAddr", "ctpvNm"

    def _fetch_accident_zone(self):
        """보행자 교통사고 다발지점 (도로교통공단 TAAS, JSON)."""
        import json as _json
        from shapely.geometry import shape

        SEOUL_GU_CODES = [
            "110", "140", "170", "200", "215", "230", "260", "290", "305",
            "320", "350", "380", "410", "440", "470", "500", "530", "545",
            "560", "590", "620", "650", "680", "710", "740",
        ]
        url = "https://opendata.koroad.or.kr/data/rest/frequentzone/pedstrians"
        taas_key = os.getenv("TAAS_OPEN_API_KEY")
        items = []

        for gu in SEOUL_GU_CODES:
            page = 1
            while True:
                res = httpx.get(url, params={
                    "authKey":      taas_key,
                    "searchYearCd": "2023",
                    "siDo":         "11",
                    "guGun":        gu,
                    "type":         "json",
                    "numOfRows":    1000,
                    "pageNo":       page,
                }, timeout=30.0)
                if res.status_code != 200:
                    break
                data = res.json()
                rows = data.get("items", {}).get("item", [])
                if isinstance(rows, dict):
                    rows = [rows]
                if not rows:
                    break
                for row in rows:
                    try:
                        geom = shape(_json.loads(row["geom_json"]))
                        lat = geom.centroid.y
                        lon = geom.centroid.x
                    except Exception:
                        continue
                    items.append({
                        "spot_nm":     row.get("spot_nm"),
                        "sido_sgg_nm": row.get("sido_sgg_nm"),
                        "la":          lat,
                        "lo":          lon,
                    })
                total = data.get("totalCount", len(rows))
                if page * 1000 >= int(total or 0):
                    break
                page += 1

        return items, "la", "lo", "spot_nm", "sido_sgg_nm", "sido_sgg_nm"
