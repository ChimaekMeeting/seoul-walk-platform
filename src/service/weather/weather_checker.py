from src.client.weather_client import get_environment_info
from typing import Dict, Tuple, Any
import textwrap

class WeatherChecker:
    def __init__(self):
        self.init_message = textwrap.dedent("""
            현재 위치를 중심으로 최적의 산책로를 추천해 드릴게요.
            원하시는 산책 조건을 말씀해 주시겠어요?
            1. 코스 종류: 순환 vs 편도
            2. 도착 지점: (편도 선택 시) 목적지 명칭
            3. 산책 테마: 운동, 데이트, 반려동물 동반 등
        """).strip()
    
    def generate_init_message(self, lat: float, lon: float) -> Tuple[dict, str]:
        """
        초기 메시지를 조립하여 반환합니다.
        """
        # 날씨 검색
        weather_data = get_environment_info(lat, lon)
        weather_message = weather_data.get("display_msg")
        return weather_data, f"{weather_message}\n{self.init_message}"