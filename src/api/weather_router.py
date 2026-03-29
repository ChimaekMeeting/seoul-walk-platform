from fastapi import APIRouter, Depends
from src.service.weather.weather_checker import WeatherChecker

router = APIRouter(
    prefix="/api/weather",
    tags=["weather"]
)

# 싱글톤 인스턴스
weather_checker = WeatherChecker()

#서비스 인스턴스를 관리하는 함수(의존성 주입용)
def get_weather_checker() -> WeatherChecker:
    return weather_checker

@router.get("/")
def get_weather(
    lat: float,
    lng: float,
    service: WeatherChecker = Depends(get_weather_checker)
):
    """
    현재 위치 기반 날씨 + 대기질 반환
    """
    return service.generate_init_message(lat, lng)