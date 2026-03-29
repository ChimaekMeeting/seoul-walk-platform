from fastapi import APIRouter
from src.service.weather_service import get_weather_info

router = APIRouter(
    prefix="/api/weather",
    tags=["날씨"]
)

@router.get("")
def get_weather(
    lat: float = 37.5665,   # 위도 (기본값: 서울시청)
    lng: float = 126.9780   # 경도 (기본값: 서울시청)
):
    """
    현재 위치 기반 날씨 + 대기질 정보 반환
    사용 예시: GET /api/weather?lat=37.5665&lng=126.9780
    """
    return get_weather_info(lat=lat, lng=lng)