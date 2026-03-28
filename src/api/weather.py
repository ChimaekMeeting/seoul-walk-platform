# [이승리] 기상청 + 에어코리아 API
import requests
import os
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

# ── 대기질 상태 → 메시지 딕셔너리 ────────────────────────────
AIR_MESSAGE: dict[str, str] = {
    "좋음":   "대기질 좋음 🟢 야외 활동 최적이에요!",
    "보통":   "대기질 보통 🟡 산책하기 무난해요.",
    "나쁨":   "대기질 나쁨 🟠 마스크 착용을 권장해요.",
    "매우나쁨": "대기질 매우 나쁨 🔴 야외 활동을 자제하세요.",
}

# ── 날씨 상태 → 코스 선호도 자동 매핑 ────────────────────────
WEATHER_TO_PREFERENCE: dict[str, str | None] = {
    "맑음":     None,       # 기본 가중치 유지
    "구름많음": None,
    "흐림":     None,
    "비":       "safety",   # 비 → 안전 코스 우선
    "눈":       "safety",   # 눈 → 안전 코스 우선
    "소나기":   "safety",
}

# ── 대기질 상태 → 코스 선호도 자동 매핑 ──────────────────────
AIR_TO_PREFERENCE: dict[str, str | None] = {
    "좋음":     None,
    "보통":     None,
    "나쁨":     "safety",   # 나쁘면 실내 인접 안전 코스
    "매우나쁨": "safety",
}


# ── 메시지 반환 함수 (기존 함수 유지) ─────────────────────────
def get_weather_message(condition: str) -> str:
    return WEATHER_MESSAGE.get(condition, "날씨 정보를 불러오는 중...")

def get_air_message(condition: str) -> str:
    return AIR_MESSAGE.get(condition, "대기질 정보를 불러오는 중...")


# ── 기상청 API 호출 ────────────────────────────────────────────
def get_weather_korea(nx: int = 60, ny: int = 127) -> tuple[str, str]:
    """
    기상청 단기예보 API 호출
    nx, ny: 격자 좌표 (서울 기본값 nx=60, ny=127)
    반환: (날씨 상태, 메시지)
    """
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

        # PTY(강수형태): 0=없음, 1=비, 2=비/눈, 3=눈, 4=소나기
        # SKY(하늘상태): 1=맑음, 3=구름많음, 4=흐림
        pty_map = {"0": "없음", "1": "비", "2": "비", "3": "눈", "4": "소나기"}
        sky_map = {"1": "맑음", "3": "구름많음", "4": "흐림"}

        pty, sky = "0", "1"
        for item in items:
            if item["category"] == "PTY":
                pty = item["fcstValue"]
            if item["category"] == "SKY":
                sky = item["fcstValue"]

        # 강수 있으면 강수 우선
        if pty != "0":
            status = pty_map.get(pty, "맑음")
        else:
            status = sky_map.get(sky, "맑음")

        return status, get_weather_message(status)

    except Exception as e:
        print(f"[날씨 API 실패] {e}")
        return "맑음", get_weather_message("맑음")


# ── 에어코리아 API 호출 ────────────────────────────────────────
def get_air_quality(station: str = "서울") -> tuple[str, str]:
    """
    에어코리아 대기오염 API 호출
    station: 측정소명 (기본값: 서울)
    반환: (대기질 상태, 메시지)
    """
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

        # 1=좋음, 2=보통, 3=나쁨, 4=매우나쁨
        grade_map = {"1": "좋음", "2": "보통", "3": "나쁨", "4": "매우나쁨"}
        status = grade_map.get(str(grade), "보통")

        return status, get_air_message(status)

    except Exception as e:
        print(f"[대기질 API 실패] {e}")
        return "보통", get_air_message("보통")


# ── 날씨 + 대기질 통합 함수 ───────────────────────────────────
def get_environment_info(nx: int = 60, ny: int = 127,
                         station: str = "서울") -> dict:
    """
    날씨 + 대기질 통합 반환
    app.py에서 이 함수 하나만 호출하면 됨
    """
    weather_status, weather_msg = get_weather_korea(nx, ny)
    air_status,     air_msg     = get_air_quality(station)

    # 코스 자동 선호도 결정 (날씨 우선, 대기질로 보완)
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
    }