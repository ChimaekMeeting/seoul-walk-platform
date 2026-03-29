# [이승리] 기상청 + 에어코리아 API
import requests
import os
import math
from datetime import datetime

# ── 날씨 상태 → 메시지 딕셔너리 ──────────────────────────────
WEATHER_MESSAGE: dict[str, str] = {
    "맑음":     "산책하기 딱 좋은 날씨예요! ☀️",
    "구름많음": "구름이 조금 있지만 산책하기 좋아요 🌤",
    "흐림":     "구름이 많지만 산책 가능해요 ⛅",
    "비":       "오늘은 실내 운동을 추천해요 🌧️",
    "눈":       "눈이 와요! 미끄럼 조심하세요 ❄️",
    "소나기":   "소나기가 예상돼요. 짧은 코스로 추천해요 🌦",
}

AIR_MESSAGE: dict[str, str] = {
    "좋음":     "대기질 좋음 🟢 야외 활동 최적이에요!",
    "보통":     "대기질 보통 🟡 산책하기 무난해요.",
    "나쁨":     "대기질 나쁨 🟠 마스크 착용을 권장해요.",
    "매우나쁨": "대기질 매우 나쁨 🔴 야외 활동을 자제하세요.",
}

WEATHER_TO_PREFERENCE: dict[str, str | None] = {
    "맑음":     None,
    "구름많음": None,
    "흐림":     None,
    "비":       "safety",
    "눈":       "safety",
    "소나기":   "safety",
}

AIR_TO_PREFERENCE: dict[str, str | None] = {
    "좋음":     None,
    "보통":     None,
    "나쁨":     "safety",
    "매우나쁨": "safety",
}

def get_weather_message(condition: str) -> str:
    return WEATHER_MESSAGE.get(condition, "날씨 정보를 불러오는 중...")

def get_air_message(condition: str) -> str:
    return AIR_MESSAGE.get(condition, "대기질 정보를 불러오는 중...")

def latlon_to_grid(lat: float, lng: float) -> tuple[int, int]:
    RE = 6371.00877
    GRID = 5.0
    SLAT1, SLAT2 = 30.0, 60.0
    OLON, OLAT = 126.0, 38.0
    XO, YO = 43, 136
    DEGRAD = math.pi / 180.0

    re = RE / GRID
    slat1 = SLAT1 * DEGRAD
    slat2 = SLAT2 * DEGRAD
    olon  = OLON  * DEGRAD
    olat  = OLAT  * DEGRAD

    sn = math.log(math.cos(slat1) / math.cos(slat2))
    sn /= math.log(math.tan(math.pi * 0.25 + slat2 * 0.5) /
                   math.tan(math.pi * 0.25 + slat1 * 0.5))
    sf = math.pow(math.tan(math.pi * 0.25 + slat1 * 0.5), sn)
    sf *= math.cos(slat1) / sn
    ro = re * sf / math.pow(math.tan(math.pi * 0.25 + olat * 0.5), sn)

    ra = re * sf / math.pow(math.tan(math.pi * 0.25 + lat * DEGRAD * 0.5), sn)
    theta = lng * DEGRAD - olon
    if theta > math.pi:  theta -= 2.0 * math.pi
    if theta < -math.pi: theta += 2.0 * math.pi
    theta *= sn

    nx = int(ra * math.sin(theta) + XO + 0.5)
    ny = int(ro - ra * math.cos(theta) + YO + 0.5)
    return nx, ny

def get_weather_korea(nx: int = 60, ny: int = 127) -> tuple[str, str]:
    api_key = os.getenv("WEATHER_API_KEY", "")
    if not api_key:
        return "맑음", get_weather_message("맑음")

    try:
        now       = datetime.now()
        date      = now.strftime("%Y%m%d")
        hours     = [2, 5, 8, 11, 14, 17, 20, 23]
        base_hour = max([h for h in hours if h <= now.hour], default=23)
        base_time = f"{base_hour:02d}00"

        url    = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
        params = {
            "serviceKey": api_key,
            "pageNo":     1,
            "numOfRows":  100,
            "dataType":   "JSON",
            "base_date":  date,
            "base_time":  base_time,
            "nx":         nx,
            "ny":         ny,
        }
        resp  = requests.get(url, params=params, timeout=5)
        items = resp.json()["response"]["body"]["items"]["item"]

        pty_map = {"0": "없음", "1": "비", "2": "비", "3": "눈", "4": "소나기"}
        sky_map = {"1": "맑음", "3": "구름많음", "4": "흐림"}

        pty, sky = "0", "1"
        for item in items:
            if item["category"] == "PTY":
                pty = item["fcstValue"]
            if item["category"] == "SKY":
                sky = item["fcstValue"]

        if pty != "0":
            status = pty_map.get(pty, "맑음")
        else:
            status = sky_map.get(sky, "맑음")

        return status, get_weather_message(status)

    except Exception as e:
        print(f"[날씨 API 실패] {e}")
        return "맑음", get_weather_message("맑음")

def get_air_quality(station: str = "서울") -> tuple[str, str]:
    api_key = os.getenv("AIR_API_KEY", "")
    if not api_key:
        return "좋음", get_air_message("좋음")

    try:
        url    = "http://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getMsrstnAcctoRltmMesureDnsty"
        params = {
            "serviceKey":  api_key,
            "returnType":  "json",
            "numOfRows":   1,
            "pageNo":      1,
            "stationName": station,
            "dataTerm":    "DAILY",
            "ver":         "1.0",
        }
        resp  = requests.get(url, params=params, timeout=5)
        item  = resp.json()["response"]["body"]["items"][0]
        grade = item.get("pm10Grade1h", "1")

        grade_map = {"1": "좋음", "2": "보통", "3": "나쁨", "4": "매우나쁨"}
        status = grade_map.get(str(grade), "보통")

        return status, get_air_message(status)

    except Exception as e:
        print(f"[대기질 API 실패] {e}")
        return "보통", get_air_message("보통")

def get_environment_info(lat: float = 37.5665,
                         lng: float = 126.9780) -> dict:
    nx, ny = latlon_to_grid(lat, lng)
    weather_status, weather_msg = get_weather_korea(nx, ny)
    air_status,     air_msg     = get_air_quality()

    auto_pref = (
        WEATHER_TO_PREFERENCE.get(weather_status) or
        AIR_TO_PREFERENCE.get(air_status)
    )

    return {
        "weather_status": weather_status,
        "weather_msg":    weather_msg,
        "air_status":     air_status,
        "air_msg":        air_msg,
        "auto_pref":      auto_pref,
        "display_msg":    f"{weather_msg}\n{air_msg}",
        "env_data": {
            "weather":   weather_status,
            "air":       air_status,
            "auto_pref": auto_pref,
            "lat":       lat,
            "lng":       lng,
        }
    }