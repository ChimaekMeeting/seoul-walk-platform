from fastapi import APIRouter, Depends
from src.infrastructure.external.client.weather_client import WeatherClient
from src.interfaces.dependencies import get_weather_client

router = APIRouter(
    prefix="/api/weather",
    tags=["weather"]
)

@router.get("")
async def get_weather(
    lat: float,
    lon: float,
    service: WeatherClient = Depends(get_weather_client)
):
    """
    현재 위치 기반 날씨와 대기질을 반환합니다.
    """
    return await service.generate_init_message(lat, lon)