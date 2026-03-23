# [박세은] 테스트 케이스
from src.db.connection import health_check
from src.api.weather import get_weather_message

def test_db_connection():
    assert health_check() is True

def test_weather_message_known():
    assert "☀️" in get_weather_message("맑음")
