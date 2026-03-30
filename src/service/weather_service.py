# src/service/weather_service.py
from src.client.weather_client import get_environment_info

def get_weather_info(lat: float, lng: float):
    """
    client 레이어 호출 (비즈니스 로직 확장 가능)
    """
    return get_environment_info(lat, lng)