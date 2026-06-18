import os
import httpx
from dotenv import load_dotenv

load_dotenv()


class PublicSource:
    def __init__(self):
        self.api_key = os.getenv("PUBLIC_DATA_API_KEY")

    def clean(
        self,
        items: list[dict],
        cols: list[str],
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
            # 필요한 컬럼 추출
            extracted = {k: item.get(k) for k in cols}

            # 결측치 제거
            if any(v in (None, "", "null") for v in extracted.values()):
                continue

            # 서울 필터링
            if city_key and city_value not in str(item.get(city_key, "")):
                continue

            # 경위도 기반 중복 제거
            coord = (extracted.get(lat_key), extracted.get(lon_key))
            if coord in seen:
                continue
            seen.add(coord)

            result.append(extracted)

        return result