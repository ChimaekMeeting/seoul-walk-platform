# ================================================================
# 파일명 : banner_service.py
# 위치   : src/service/banner_service.py
# 역할   : 시간대 + 날씨 + 이벤트 기반으로 배너 목록을 결정하는 서비스
# ================================================================

from src.data.collectors.marathon_crawler import fetch_marathon_events
from datetime import datetime, date
import random
import re
import streamlit as st


# ── 고정/시즌 배너 데이터 ──────────────────────────────────────
BANNERS = {
    "season": {
        "hot_sunny":   {"emoji": "🌳", "text": "오늘 덥죠? 그늘 가득한 숲길 어떠세요?",  "sub": "더위를 피하는 나만의 산책 코스"},
        "hot_humid":   {"emoji": "🌊", "text": "습한 날엔 물가 바람이 최고예요",         "sub": "시원한 물가 코스 추천"},
        "hot_morning": {"emoji": "🌅", "text": "더워지기 전에 먼저 걸어볼까요?",         "sub": "상쾌한 새벽 산책 코스"},
    },
    "fixed": {
        "dog":     {"emoji": "🐶", "text": "강아지랑 함께 걷기 좋은 길이에요",         "sub": "반려견 동반 가능 코스"},
        "healing": {"emoji": "🌿", "text": "조용하게 걷고 싶을 때 추천해요",           "sub": "힐링 숲길 코스"},
        "night":   {"emoji": "🌃", "text": "저녁에 걷기 좋은 야경 코스예요",           "sub": "야경 명소 산책로"},
    }
}


# ── 이벤트 관련 함수 ───────────────────────────────────────────

@st.cache_data(ttl=3600)  # 1시간마다 갱신
def get_events_cached() -> list[dict]:
    """크롤링 결과를 1시간 캐싱"""
    seoul   = fetch_marathon_events("서울")
    gyeonggi = fetch_marathon_events("경기")
    incheon = fetch_marathon_events("인천")
    return seoul + gyeonggi + incheon


def get_active_event() -> dict | None:
    """D-14 이내 이벤트 반환"""
    today = date.today()
    for event in get_events_cached():
        diff = (event["date"] - today).days
        if -1 <= diff <= 14:
            return {**event, "diff": diff}
    return None


def _get_event_text(event: dict) -> dict:
    """D-day에 따라 배너 문구를 다르게 반환"""
    diff  = event["diff"]
    name  = event["name"]
    loc   = event["location"]
    emoji = event["emoji"]

    if diff == 0:
        text = f"오늘 {name} 대회날이에요!"
        sub  = f"{loc} 근처 산책코스 추천해드려요"
    elif diff <= 3:
        text = f"이번 주말 {name}!"
        sub  = f"D-{diff} · {loc} · 코스 미리 확인해보세요"
    else:
        text = f"{name} 미리 준비해볼까요?"
        sub  = f"D-{diff} · {loc}"

    return {"emoji": emoji, "text": text, "sub": sub}

def _get_event_text(event: dict) -> dict:
    diff  = event["diff"]
    name  = event["name"]
    loc   = event["location"]
    emoji = event["emoji"]
    event_date = event["date"]  

    if diff == 0:
        text = f"오늘 {name} 대회날이에요!"
        sub  = f"{loc} 근처 산책코스 추천해드려요"
    elif diff <= 3:
        text = f"이번 주말 {name}!"
        sub  = f"D-{diff} · {loc} · 코스 미리 확인해보세요"
    else:
        text = f"{name} 미리 준비해볼까요?"
        sub  = f"D-{diff} · {loc}"

    return {
        "emoji":    emoji,
        "text":     text,
        "sub":      sub,
        "is_event": True,           # ← 추가
        "date":     str(event_date), # ← 추가
        "location": loc,             # ← 추가
        "url": f"https://marathongo.co.kr/raceDetail/domestic/{event.get('slug', '')}"  # ← 추가
    }

# ── 날씨 헬퍼 함수 ─────────────────────────────────────────────

def _is_hot(weather_msg: str) -> bool:
    """weather_msg에서 기온을 파싱해 23도 이상이면 True 반환"""
    match = re.search(r"[-+]?\d+(\.\d+)?", weather_msg)
    if match:
        try:
            return float(match.group()) >= 23
        except ValueError:
            pass
    return False


def _is_humid(weather_status: str) -> bool:
    """날씨 상태에 흐림/습함 관련 키워드가 있으면 True 반환"""
    keywords = ["흐림", "구름", "습", "비"]
    return any(k in weather_status for k in keywords)


# ── 메인 함수 ──────────────────────────────────────────────────

def get_banner(weather: dict, hour: int | None = None) -> dict:
    """단일 배너 반환 (하위 호환용)"""
    banners = get_banner_list(weather, hour)
    return banners[0] if banners else BANNERS["fixed"]["healing"]


def get_banner_list(weather: dict, hour: int | None = None) -> list:
    """
    홈 화면에 노출할 배너 목록 전체를 반환합니다.
    우선순위: 이벤트 → 시즌 → 고정
    """
    if hour is None:
        hour = datetime.now().hour

    status = weather.get("weather_status", "")
    msg    = weather.get("weather_msg", "")
    banners = []

    # 1순위: 이벤트 배너
    active_event = get_active_event()
    if active_event:
        banners.append(_get_event_text(active_event))

    # 2순위: 시즌 배너 (날씨 기반)
    if _is_hot(msg):
        if 6 <= hour < 9:
            banners.append(BANNERS["season"]["hot_morning"])
        elif _is_humid(status):
            banners.append(BANNERS["season"]["hot_humid"])
        else:
            banners.append(BANNERS["season"]["hot_sunny"])

    # 3순위: 고정 배너 (시간대 기반 전체 추가)
    if hour < 17:
        keys = ["dog", "healing"]
    elif hour < 21:
        keys = ["dog", "healing", "night"]
    else:
        keys = ["night"]

    for key in keys:
        banners.append(BANNERS["fixed"][key])

    return banners