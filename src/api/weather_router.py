# src/api/weather_router.py
from fastapi import APIRouter, Depends
from src.service.weather.weather_checker import WeatherChecker
from src.api.dependencies import get_weather_checker

router = APIRouter(
    prefix="/api/weather",
    tags=["weather"]
)

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
