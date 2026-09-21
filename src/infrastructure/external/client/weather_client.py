import asyncio
from datetime import datetime, timedelta
import logging
import math

import httpx

from src.config.settings import settings
from src.infrastructure.cache.repository.weather_cache_repository import (
    WeatherCacheRepository,
)
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
        # 날씨와 대기질은 서로 독립이다. 한쪽에서 예외가 나도 다른 쪽 결과를 버리지 않도록
        # 각각 예외를 잡아 None으로 돌려준다(실패 시 None은 기존 응답 형식과 같다).
        weather_status, air_status = await asyncio.gather(
            self._run_safely("weather", self._get_weather_cached(lat, lon)),
            self._run_safely("air_quality", self._get_air_quality_cached(lat, lon)),
        )

        return weather_status, air_status

    async def _run_safely(self, name: str, coroutine):
        try:
            return await coroutine
        except Exception as error:
            logger.warning(
                "%s_unexpected_error | error_type=%s",
                name,
                type(error).__name__,
            )
            return None

    async def _get_weather_cached(self, lat: float, lon: float):
        """같은 기상청 격자(nx, ny) 안에서는 캐시된 날씨를 재사용한다."""
        nx, ny = self.get_nx_and_ny(lat, lon)
        cached = await self._read_cache(
            "weather", WeatherCacheRepository.get_weather, nx, ny
        )
        if cached is not None:
            return cached

        weather = await self.get_weather(lat, lon)
        if weather:
            await self._write_cache(
                "weather", WeatherCacheRepository.save_weather, nx, ny, weather
            )
        return weather

    async def _get_air_quality_cached(self, lat: float, lon: float):
        """캐시가 있으면 카카오 주소 변환과 에어코리아 호출을 모두 건너뛴다."""
        nx, ny = self.get_nx_and_ny(lat, lon)
        cached = await self._read_cache(
            "air_quality", WeatherCacheRepository.get_air_quality, nx, ny
        )
        if cached is not None:
            return cached

        air = await self.get_air_quality(lat, lon)
        # 실패(None)와 자치구를 못 찾은 경우({})는 저장하지 않는다. 저장하면 복구된 뒤에도
        # TTL 동안 빈 값이 계속 나간다.
        if air:
            await self._write_cache(
                "air_quality", WeatherCacheRepository.save_air_quality, nx, ny, air
            )
        return air

    async def _read_cache(self, name: str, reader, nx: int, ny: int):
        # 캐시(Valkey) 장애가 API 실패로 번지지 않도록 조회 실패는 캐시 미스로 취급한다.
        try:
            return await reader(nx, ny)
        except Exception as error:
            logger.warning(
                "%s_cache_read_failed | error_type=%s",
                name,
                type(error).__name__,
            )
            return None

    async def _write_cache(self, name: str, writer, nx: int, ny: int, data: dict):
        try:
            await writer(nx, ny, data)
        except Exception as error:
            logger.warning(
                "%s_cache_write_failed | error_type=%s",
                name,
                type(error).__name__,
            )

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
        # 카카오 주소 변환이 실패(한도 초과 등)해도 예외를 밖으로 내보내지 않고 다른 실패와
        # 같이 None으로 처리한다.
        try:
            place_info = await self.kakao_client.get_address_from_coords(lat, lon)
        except Exception as error:
            logger.warning(
                "air_quality_address_failed | error_type=%s | detail=%s",
                type(error).__name__,
                error,
            )
            return None
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
