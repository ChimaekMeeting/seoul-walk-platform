import httpx
import os
import math
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv

from src.infrastructure.external.schema.weather_schema import EnvironmentInfo

load_dotenv()

WEATHER_MESSAGE: dict[str, str] = {
    "맑음":     "산책하기 딱 좋은 날씨예요! ☀️",
    "구름많음": "구름이 조금 있지만 산책하기 좋아요 🌤",
    "흐림":     "구름이 많지만 산책 가능해요 ⛅",
    "비":       "오늘은 실내 운동을 추천해요 🌧️",
    "눈":       "눈이 와요! 미끄럼 조심하세요 ❄️",
    "소나기":   "소나기가 예상돼요. 짧은 코스로 추천해요 🌦",
}

AIR_MESSAGE: dict[str, str] = {
    "좋음":     "대기질 좋음 🟢 야외 활동 최적이에요!",
    "보통":     "대기질 보통 🟡 산책하기 무난해요.",
    "나쁨":     "대기질 나쁨 🟠 마스크 착용을 권장해요.",
    "매우나쁨": "대기질 매우 나쁨 🔴 야외 활동을 자제하세요.",
}


class WeatherClient:
    def __init__(self):
        self.WEATHER_URL = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
        self.AIR_URL     = "http://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getMsrstnAcctoRltmMesureDnsty"
        self.WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")

    def get_weather_message(self, condition: str) -> str:
        return WEATHER_MESSAGE.get(condition)

    def get_air_message(self, condition: str) -> str:
        return AIR_MESSAGE.get(condition)

    async def get_environment_info(self, lat: float, lon: float) -> EnvironmentInfo:
        """
        날씨 + 대기질을 병렬 조회 후 통합 결과 반환
        """
        nx, ny = self._latlon_to_grid(lat, lon)
        (weather_status, weather_msg), (air_status, air_msg) = await asyncio.gather(
            self._get_weather(nx, ny),
            self._get_air_quality(),
        )

        return EnvironmentInfo(
            weather_status=weather_status,
            weather_msg=weather_msg,
            air_status=air_status,
            air_msg=air_msg,
            display_msg=f"{weather_msg}\n{air_msg}",
        )

    async def _get_weather(self, nx: int, ny: int) -> tuple[str, str]:
        """
        날씨 예보 조회 및 상태 결정
        """
        base_date, base_time = self._get_base_time()
        items = await self._fetch_weather_forecast(nx, ny, base_date, base_time)
        if items is None:
            return "맑음", self.get_weather_message("맑음")

        status = self._parse_weather_status(items)
        return status, self.get_weather_message(status)

    async def _get_air_quality(self, station: str = "서울") -> tuple[str, str]:
        """
        대기질 조회 및 상태 결정
        """
        item = await self._fetch_air_quality_data(station)
        if item is None:
            return "보통", self.get_air_message("보통")

        status = self._parse_air_status(item)
        return status, self.get_air_message(status)

    async def _fetch_weather_forecast(
        self, nx: int, ny: int, base_date: str, base_time: str
    ) -> list | None:
        """
        날씨 예보 API HTTP 요청
        """
        params = {
            "serviceKey": self.WEATHER_API_KEY,
            "pageNo":     1,
            "numOfRows":  100,
            "dataType":   "JSON",
            "base_date":  base_date,
            "base_time":  base_time,
            "nx":         nx,
            "ny":         ny,
        }
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(self.WEATHER_URL, params=params, timeout=5)
                return res.json()["response"]["body"]["items"]["item"]
        except Exception:
            return None

    async def _fetch_air_quality_data(self, station: str) -> dict | None:
        """
        대기질 API HTTP 요청
        """
        params = {
            "serviceKey":  self.WEATHER_API_KEY,
            "returnType":  "json",
            "numOfRows":   1,
            "pageNo":      1,
            "stationName": station,
            "dataTerm":    "DAILY",
            "ver":         "1.0",
        }
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(self.AIR_URL, params=params, timeout=5)
                return res.json()["response"]["body"]["items"][0]
        except Exception:
            return None

    def _parse_weather_status(self, items: list) -> str:
        """
        예보 아이템에서 날씨 상태 문자열 추출
        """
        pty_map = {"0": "없음", "1": "비", "2": "비", "3": "눈", "4": "소나기"}
        sky_map = {"1": "맑음", "3": "구름많음", "4": "흐림"}

        pty, sky = "0", "1"
        for item in items:
            if item["category"] == "PTY":
                pty = item["fcstValue"]
            if item["category"] == "SKY":
                sky = item["fcstValue"]

        if pty != "0":
            return pty_map.get(pty, "맑음")
        return sky_map.get(sky, "맑음")

    def _parse_air_status(self, item: dict) -> str:
        """
        대기질 아이템에서 등급 문자열 추출
        """
        grade_map = {"1": "좋음", "2": "보통", "3": "나쁨", "4": "매우나쁨"}
        grade = item.get("pm10Grade1h", "1")
        return grade_map.get(str(grade), "보통")

    def _get_base_time(self) -> tuple[str, str]:
        """
        API 호출에 사용할 발표 기준 날짜·시간 계산
        """
        now = datetime.now()
        hours = [2, 5, 8, 11, 14, 17, 20, 23]
        valid_hours = [h for h in hours if h < now.hour]

        if not valid_hours:
            return (now - timedelta(days=1)).strftime("%Y%m%d"), "2300"

        base_hour = max(valid_hours)
        return now.strftime("%Y%m%d"), f"{base_hour:02d}00"

    @staticmethod
    def _latlon_to_grid(lat: float, lon: float) -> tuple[int, int]:
        """
        위경도 → 기상청 격자 좌표 변환
        """
        RE = 6371.00877
        GRID = 5.0
        SLAT1, SLAT2 = 30.0, 60.0
        OLON, OLAT = 126.0, 38.0
        XO, YO = 43, 136
        DEGRAD = math.pi / 180.0

        re    = RE / GRID
        slat1 = SLAT1 * DEGRAD
        slat2 = SLAT2 * DEGRAD
        olon  = OLON  * DEGRAD
        olat  = OLAT  * DEGRAD

        sn = math.log(math.cos(slat1) / math.cos(slat2))
        sn /= math.log(
            math.tan(math.pi * 0.25 + slat2 * 0.5) /
            math.tan(math.pi * 0.25 + slat1 * 0.5)
        )
        sf = math.pow(math.tan(math.pi * 0.25 + slat1 * 0.5), sn)
        sf *= math.cos(slat1) / sn
        ro = re * sf / math.pow(math.tan(math.pi * 0.25 + olat * 0.5), sn)

        ra    = re * sf / math.pow(math.tan(math.pi * 0.25 + lat * DEGRAD * 0.5), sn)
        theta = lon * DEGRAD - olon
        if theta >  math.pi: theta -= 2.0 * math.pi
        if theta < -math.pi: theta += 2.0 * math.pi
        theta *= sn

        nx = int(ra * math.sin(theta) + XO + 0.5)
        ny = int(ro - ra * math.cos(theta) + YO + 0.5)
        return nx, ny