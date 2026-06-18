import os
from dotenv import load_dotenv

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


class KakaoSource:
    def __init__(self):
        self.api_key = os.getenv("KAKAO_API_KEY")
        self.headers = {"Authorization": f"KakaoAK {self.api_key}"}

    def clean(
        self,
        items: list[dict],
        cols: list[str],
        lat_key: str = "y",
        lon_key: str = "x",
    ) -> list[dict]:
        """
        기본 전처리를 수행합니다.
        """
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

            result.append(extracted)

        return result
