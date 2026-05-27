from fastapi import APIRouter, Depends
from src.service.weather.weather_checker import WeatherChecker
from src.interfaces.dependencies import get_weather_checker

router = APIRouter(
    prefix="/api/weather",
    tags=["weather"]
)

@router.get("/")
async def get_weather(
    lat: float,
    lon: float,
    service: WeatherChecker = Depends(get_weather_checker)
):
    """
    현재 위치 기반 날씨와 대기질을 반환합니다.
    """
    return await service.generate_init_message(lat, lon)
