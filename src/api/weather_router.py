from fastapi import APIRouter
from src.service.weather_service import get_weather_info

router = APIRouter(
    prefix="/api/weather",
    tags=["weather"]
)

@router.get("")
def get_weather(lat: float, lng: float):
    """
    현재 위치 기반 날씨 + 대기질 반환
    """
    return get_weather_info(lat, lng)