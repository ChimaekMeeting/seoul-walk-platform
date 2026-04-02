# [이승리] 기상청 + 에어코리아 API
# src/client/weather_client.py

import requests
import os
import math
from datetime import datetime, timedelta
from dotenv import load_dotenv

# .env 파일에서 API KEY 불러오기 (날씨/대기질 API 사용)
load_dotenv()

# ── 날씨 상태 → 사용자에게 보여줄 메시지 매핑 ──────────────────────────────
# 기상청 API에서 받은 상태값을 사람이 읽기 좋은 문장으로 변환
WEATHER_MESSAGE: dict[str, str] = {
    "맑음":     "산책하기 딱 좋은 날씨예요! ☀️",
    "구름많음": "구름이 조금 있지만 산책하기 좋아요 🌤",
    "흐림":     "구름이 많지만 산책 가능해요 ⛅",
    "비":       "오늘은 실내 운동을 추천해요 🌧️",
    "눈":       "눈이 와요! 미끄럼 조심하세요 ❄️",
    "소나기":   "소나기가 예상돼요. 짧은 코스로 추천해요 🌦",
}

# ── 대기질 상태 → 사용자 메시지 매핑 ──────────────────────────────
AIR_MESSAGE: dict[str, str] = {
    "좋음":     "대기질 좋음 🟢 야외 활동 최적이에요!",
    "보통":     "대기질 보통 🟡 산책하기 무난해요.",
    "나쁨":     "대기질 나쁨 🟠 마스크 착용을 권장해요.",
    "매우나쁨": "대기질 매우 나쁨 🔴 야외 활동을 자제하세요.",
}

# ── 날씨/대기질 기반 추천 가중치 (후속 추천 로직에서 사용 가능) ─────────
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

# 상태 → 메시지 변환 함수
def get_weather_message(condition: str) -> str:
    return WEATHER_MESSAGE.get(condition, "날씨 정보를 불러오는 중...")

def get_air_message(condition: str) -> str:
    return AIR_MESSAGE.get(condition, "대기질 정보를 불러오는 중...")

# ── 위도/경도 → 기상청 격자 변환 ──────────────────────────────
# 기상청 API는 lat/lng 대신 nx, ny 좌표를 사용하기 때문에 변환 필요
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

# ── 기상청 API 호출 (날씨 정보) ──────────────────────────────
def get_weather_korea(nx: int = 60, ny: int = 127) -> tuple[str, str]:
    api_key = os.getenv("WEATHER_API_KEY", "")
    if not api_key:
        return "맑음", get_weather_message("맑음")

    try:
        now = datetime.now()

        # 기상청 API는 특정 발표 시간 기준으로 데이터 제공
        hours = [2, 5, 8, 11, 14, 17, 20, 23]
        valid_hours = [h for h in hours if h < now.hour]

        if not valid_hours:
            base_hour = 23
            base_date = (now - timedelta(days=1)).strftime("%Y%m%d")
        else:
            base_hour = max(valid_hours)
            base_date = now.strftime("%Y%m%d")

        base_time = f"{base_hour:02d}00"

        url = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
        params = {
            "serviceKey": api_key,
            "pageNo": 1,
            "numOfRows": 100,
            "dataType": "JSON",
            "base_date": base_date,
            "base_time": base_time,
            "nx": nx,
            "ny": ny,
        }

        resp = requests.get(url, params=params, timeout=5)
        items = resp.json()["response"]["body"]["items"]["item"]

        # 날씨 상태 코드 추출
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

# ── GPS 기반 간단 지역 분기 (측정소 선택용) ──────────────────────────────
# AirKorea API는 lat/lng를 직접 받지 않기 때문에
# 좌표를 기반으로 간단하게 지역을 나눠서 측정소를 선택함
def get_station_by_location(lat, lng):
    if lat > 37.55:
        return "종로구"
    elif lat < 37.5 and lng > 127.0:
        return "강남구"
    elif lng < 126.95:
        return "마포구"
    elif lng > 127.1:
        return "송파구"
    else:
        return "용산구"
    
# ── 에어코리아 API 호출 (대기질 정보) ──────────────────────────────
def get_air_quality(lat: float, lng: float) -> tuple[str, str]:
    api_key = os.getenv("AIR_KOREA_API_KEY", "")
    print("API KEY 존재 여부:", bool(api_key))
    if not api_key:
        return "좋음", get_air_message("좋음")

    try:
        # GPS 좌표 기반으로 측정소 선택
        station = get_station_by_location(lat, lng)
        print("선택된 측정소:", station)

        url = "http://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getMsrstnAcctoRltmMesureDnsty"

        params = {
            "serviceKey": api_key,
            "returnType": "json",
            "numOfRows": 10,
            "pageNo": 1,
            "stationName": station,
            "dataTerm": "DAILY",
            "ver": "1.0",
        }

        resp = requests.get(url, params=params, timeout=5)

        # JSON 파싱 (안정성 처리)
        try:
            data = resp.json()
        except Exception:
            print("JSON 파싱 실패")
            return "보통", get_air_message("보통")

        # 데이터 추출
        items = data.get("response", {}).get("body", {}).get("items", [])

        if not items:
            print("items 없음")
            return "보통", get_air_message("보통")

        # 가장 최신 데이터 선택
        latest_item = max(items, key=lambda x: x.get("dataTime", ""))

        # 미세먼지 값 (디버깅/확인용)
        pm10 = latest_item.get("pm10Value")
        pm25 = latest_item.get("pm25Value")

        print("미세먼지(PM10):", pm10)
        print("초미세먼지(PM2.5):", pm25)

        # 통합 대기 지수
        khai_value = int(latest_item.get("khaiValue", "50"))

        # 상태 분류
        if khai_value <= 50:
            status = "좋음"
        elif khai_value <= 100:
            status = "보통"
        elif khai_value <= 250:
            status = "나쁨"
        else:
            status = "매우나쁨"

        return status, get_air_message(status)

    except Exception as e:
        print(f"[대기질 API 실패] {e}")
        return "보통", get_air_message("보통")
    
# ── 최종 통합 함수 (외부에서 호출하는 핵심 함수) ──────────────────────────────
def get_environment_info(lat: float = 37.5665,
                         lng: float = 126.9780) -> dict:
    # 날씨
    nx, ny = latlon_to_grid(lat, lng)
    weather_status, weather_msg = get_weather_korea(nx, ny)

    # 대기질
    air_status, air_msg = get_air_quality(lat, lng)

    # 추천 가중치
    auto_pref = (
        WEATHER_TO_PREFERENCE.get(weather_status) or
        AIR_TO_PREFERENCE.get(air_status)
    )

    # 팀원들과 공유되는 반환 구조
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