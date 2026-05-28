from typing import Literal
from pydantic import BaseModel

WeatherStatus = Literal["맑음", "구름많음", "흐림", "비", "눈", "소나기"]
AirStatus = Literal["좋음", "보통", "나쁨", "매우나쁨"]


class EnvironmentInfo(BaseModel):
    """
    날씨와 대기질 조회 결과 및 사용자에게 표시할 메시지를 나타냅니다.
    """
    weather_status: str
    weather_msg: str
    air_status: str
    air_msg: str
    display_msg: str
