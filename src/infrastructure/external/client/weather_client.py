import asyncio
from datetime import datetime, timedelta
import logging
import math

import httpx

from src.config.settings import settings
from src.infrastructure.external.client.kakao_client import KakaoClient

logger = logging.getLogger(__name__)


class WeatherClient:
    def __init__(
        self,
        kakao_client: KakaoClient,
        weather_api_key: str | None = None,
        air_korea_api_key: str | None = None,
    ):
        # 기상청과 에어코리아는 공공데이터포털에서 각각 발급·활성화한 키를 쓴다.
        # 전용 키가 없는 기존 환경만 PUBLIC_DATA_API_KEY로 호환한다.
        self.weather_api_key = (
            weather_api_key
            if weather_api_key is not None
            else settings.WEATHER_API_KEY or settings.PUBLIC_DATA_API_KEY
        )
        self.air_korea_api_key = (
            air_korea_api_key
            if air_korea_api_key is not None
            else settings.AIR_KOREA_API_KEY or settings.PUBLIC_DATA_API_KEY
        )
        self.kakao_client = kakao_client

    async def get_environment_info(self, lat: float, lon: float):
        weather_status, air_status = await asyncio.gather(
            self.get_weather(lat, lon),
            self.get_air_quality(lat, lon),
        )

        return weather_status, air_status

    async def get_weather(self, lat: float, lon: float):
        """
        날씨 데이터를 조회합니다.
        """
        url = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst"

        base_date, base_time = self.get_base_datetime()
        nx, ny = self.get_nx_and_ny(lat, lon)

        params = {
            "serviceKey": self.weather_api_key,
            "pageNo":     1,
            "numOfRows":  10,
            "dataType":   "JSON",
            "base_date": base_date,
            "base_time": base_time,
            "nx": nx,
            "ny": ny
        }

        # PTY(강수형태) 코드 → 상태값 매핑
        PTY_map = {
            0: "없음",
            1: "비",
            2: "비/눈",
            3: "눈",
            5: "빗방울",
            6: "빗방울눈날림",
            7: "눈날림",
        }
        rename_map = {
            "PTY": ("precipitation_type", ""),  # 강수형태
            "REH": ("humidity", "%"),           # 습도
            "RN1": ("precipitation_1h", "mm"),  # 1시간 강수량
            "T1H": ("temperature", "℃"),        # 기온
            "WSD": ("wind_speed", "m/s"),       # 풍속
        }

        async with httpx.AsyncClient(timeout=10) as client:
            try:
                res = await client.get(url, params=params)
                res.raise_for_status()
                items = res.json()["response"]["body"]["items"]["item"]
                data = {item["category"]: item["obsrValue"] for item in items}
                return {
                    new_key: (PTY_map.get(int(float(data[key])), "없음") + unit) if key == "PTY"
                             else str(data[key]) + unit
                    for key, (new_key, unit) in rename_map.items()
                    if key in data
                }
            except Exception as error:
                logger.warning(
                    "weather_fetch_failed | error_type=%s",
                    type(error).__name__,
                )
                return None

    async def get_air_quality(self, lat: float, lon: float):
        """
        대기질 정보를 조회합니다.
        """
        url = "https://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getMsrstnAcctoRltmMesureDnsty"

        station_name = ""
        place_info = await self.kakao_client.get_address_from_coords(lat, lon)
        for p in place_info.place_address.split():
            if "구" in p:
                station_name = p
                break
            
        if station_name == "":
            print("사용자가 위치한 자치구를 찾지 못했습니다.")
            return {}

        params = {
            "serviceKey": self.air_korea_api_key,
            "returnType": "json",
            "numOfRows": 1,
            "pageNo": 1,
            "stationName": station_name,
            "dataTerm": "DAILY",
            "ver": "1.0"
        }

        rename_map = {
            "khaiValue": ("air_quality_index", ""),  # 통합대기환경지수
            "so2Value":  ("so2", "ppm"),             # 이산화황
            "coValue":   ("co", "ppm"),              # 일산화탄소
            "pm10Value": ("pm10", "㎍/㎥"),           # 미세먼지
            "pm25Value": ("pm25", "㎍/㎥"),           # 초미세먼지
            "no2Value":  ("no2", "ppm"),             # 이산화질소
            "o3Value":   ("o3", "ppm"),              # 오존
        }

        async with httpx.AsyncClient() as client:
            try:
                res = await client.get(url=url, params=params)
                res.raise_for_status()
                data = res.json()["response"]["body"]["items"][0]
                return {
                    new_key: str(v) + unit
                    for key, (new_key, unit) in rename_map.items()
                    if key in data and (v := data.get(key)) is not None and v != "-"
                }
            except Exception as error:
                logger.warning(
                    "air_quality_fetch_failed | error_type=%s",
                    type(error).__name__,
                )
                return None

    def get_base_datetime(self) -> tuple[str, str]:
        """
        base_date, base_time을 계산합니다.
        초단기실황(getUltraSrtNcst)은 정시 관측 데이터가 약 40분 뒤에 제공되므로,
        현재 분이 40분 미만이면 직전 시각을 사용합니다.
        """
        now = datetime.now()

        if now.minute < 40:
            now = now - timedelta(hours=1)

        return now.strftime("%Y%m%d"), now.strftime("%H00")
    
    def get_nx_and_ny(self, lat: float, lon: float) -> tuple[int, int]:
        """
        경위도를 기상청 격자 좌표(nx, ny)로 변환합니다.
        """
        RE, GRID = 6371.00877, 5.0
        SLAT1, SLAT2 = 30.0, 60.0
        OLON, OLAT = 126.0, 38.0
        XO, YO = 43, 136
        D = math.pi / 180.0

        re = RE / GRID
        sn = math.log(math.cos(SLAT1 * D) / math.cos(SLAT2 * D))
        sn /= math.log(
            math.tan(math.pi * 0.25 + SLAT2 * D * 0.5) /
            math.tan(math.pi * 0.25 + SLAT1 * D * 0.5)
        )
        sf = math.pow(math.tan(math.pi * 0.25 + SLAT1 * D * 0.5), sn)
        sf *= math.cos(SLAT1 * D) / sn
        ro = re * sf / math.pow(math.tan(math.pi * 0.25 + OLAT * D * 0.5), sn)

        ra = re * sf / math.pow(math.tan(math.pi * 0.25 + lat * D * 0.5), sn)
        theta = (lon - OLON) * D
        if theta > math.pi:
            theta -= 2.0 * math.pi
        if theta < -math.pi:
            theta += 2.0 * math.pi
        theta *= sn

        nx = int(ra * math.sin(theta) + XO + 0.5)
        ny = int(ro - ra * math.cos(theta) + YO + 0.5)
        return nx, ny


if __name__ == "__main__":
    client = WeatherClient(KakaoClient())
    asyncio.run(client.get_environment_info(lat=37.5663, lon=126.9779))
