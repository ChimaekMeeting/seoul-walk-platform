# [이승리] 기상청 + 에어코리아 API
WEATHER_MESSAGE: dict[str, str] = {
    "맑음": "산책하기 딱 좋은 날씨예요! ☀️",
    "흐림": "구름이 많지만 산책 가능해요 ⛅",
    "비":   "오늘은 실내 운동을 추천해요 🌧️",
}
def get_weather_message(condition: str) -> str:
    return WEATHER_MESSAGE.get(condition, "날씨 정보를 불러오는 중...")
