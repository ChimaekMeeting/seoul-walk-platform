from pydantic import BaseModel


class WeatherInfo(BaseModel):
    """
    get_weather() 반환값 (초단기실황).
    각 값은 "수치 + 단위" 형태의 문자열이며, 관측값이 없는 항목은 생략될 수 있습니다.
    예: {"temperature": "23.5℃", "humidity": "60%", "precipitation_type": "비"}
    """
    precipitation_type: str | None = None  # 강수형태 (없음/비/비·눈/눈/빗방울 등)
    humidity: str | None = None            # 습도 (%)
    precipitation_1h: str | None = None    # 1시간 강수량 (mm)
    temperature: str | None = None         # 기온 (℃)
    wind_speed: str | None = None          # 풍속 (m/s)


class AirQualityInfo(BaseModel):
    """
    get_air_quality() 반환값 (실시간 측정소별 대기질).
    각 값은 "수치 + 단위" 형태의 문자열이며, 측정값이 없는 항목은 생략될 수 있습니다.
    예: {"air_quality_index": "80", "pm10": "45㎍/㎥", "pm25": "20㎍/㎥"}
    """
    air_quality_index: str | None = None  # 통합대기환경지수
    so2: str | None = None                # 이산화황 (ppm)
    co: str | None = None                 # 일산화탄소 (ppm)
    pm10: str | None = None               # 미세먼지 (㎍/㎥)
    pm25: str | None = None               # 초미세먼지 (㎍/㎥)
    no2: str | None = None                # 이산화질소 (ppm)
    o3: str | None = None                 # 오존 (ppm)


class EnvironmentInfo(BaseModel):
    """
    날씨와 대기질 조회 결과를 나타냅니다.
    """
    weather: WeatherInfo = WeatherInfo()      # get_weather() 반환값 (기온, 습도, 강수형태 등)
    air: AirQualityInfo = AirQualityInfo()    # get_air_quality() 반환값 (미세먼지, 통합대기환경지수 등)
