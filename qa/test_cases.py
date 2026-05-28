# [박세은] 테스트 케이스
from src.database.postgresql import health_check
from src.infrastructure.external.client.weather_client import WeatherClient

def test_db_connection():
    assert health_check() is True

def test_weather_message_known():
    assert "☀️" in WeatherClient.get_weather_message("맑음")
