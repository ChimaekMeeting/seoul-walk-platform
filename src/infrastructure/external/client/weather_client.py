import os
import asyncio
from datetime import datetime, timedelta
import math, httpx
from dotenv import load_dotenv

from src.infrastructure.external.client.kakao_client import KakaoClient

load_dotenv()

class WeatherClient:
    def __init__(self, kakao_client: KakaoClient):
        self.api_key = os.getenv("PUBLIC_DATA_API_KEY")
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
        url = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst"

        base_date, base_time = self.get_base_datetime()
        nx, ny = self.get_nx_and_ny(lat, lon)

        params = {
            "serviceKey": self.api_key,
            "pageNo":     1,
            "numOfRows":  10,
            "dataType":   "JSON",
            "base_date": base_date,
            "base_time": base_time,
            "nx": nx,
            "ny": ny
        }

        PTY_map = { 0: "없음", 1: "비", 2: "비/눈", 3: "눈", 5: "빗방울", 6: "빗방울눈날림", 7: "눈날림" }
        rename_map = {
            "PTY": ("강수형태", ""),
            "REH": ("습도", "%"),
            "RN1": ("1시간 강수량", "mm"),
            "T1H": ("기온", "℃"),
            "WSD": ("풍속", "m/s")
        }

        async with httpx.AsyncClient(timeout=10) as client:
            try:
                res = await client.get(url, params=params)
                data = res.json().get("response").get("body").get("items").get("item")
                return {
                    new_key: PTY_map.get(data.get(key)) + unit if key == "PTY" else str(data.get(key)) + unit
                    for key, (new_key, unit) in rename_map.items()
                    if key in data
                }
                
            except Exception:
                print("날씨 데이터 조회 시 오류가 발생했습니다.")

    async def get_air_quality(self, lat: float, lon: float):
        """
        대기질 정보를 조회합니다.
        """
        url = "http://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getMsrstnAcctoRltmMesureDnsty"

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
            "serviceKey": self.api_key,
            "returnType": "json",
            "numOfRows": 1,
            "pageNo": 1,
            "stationName": station_name,
            "dataTerm": "DAILY",
            "ver": "1.0"
        }

        rename_map = {
            "KhaiValue": ("통합대기환경지수", ""),
            "so2Value":  ("이상화황", "ppm"),
            "coValue":   ("일산화탄소", "ppm"),
            "pm10Value": ("미세먼지", "㎍/㎥"),
            "pm25Value": ("초미세먼지", "㎍/㎥"),
            "no2Value":  ("이산화질소", "ppm"),
            "o3Value":   ("오존", "ppm")
        }

        async with httpx.AsyncClient() as client:
            try:
                res = await client.get(url=url, params=params)
                data = res.json().get("response").get("body").get("items")[0]
                return {new_key: str(data.get(key)) + idx for key, (new_key, idx) in rename_map.items() if key in data}
            except Exception:
                print("대기질 데이터 조회 시 오류가 발생했습니다.")

    def get_base_datetime(self) -> tuple[str, str]:
        """
        base_date, base_time을 계산합니다.
        """
        now = datetime.now()

        if now.minute < 10:
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
        if theta >  math.pi: theta -= 2.0 * math.pi
        if theta < -math.pi: theta += 2.0 * math.pi
        theta *= sn

        nx = int(ra * math.sin(theta) + XO + 0.5)
        ny = int(ro - ra * math.cos(theta) + YO + 0.5)
        return nx, ny


if __name__ == "__main__":
    client = WeatherClient(KakaoClient())
    asyncio.run(client.get_environment_info(lat=37.5663, lon=126.9779))