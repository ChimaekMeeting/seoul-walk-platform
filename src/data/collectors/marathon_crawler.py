# ================================================================
# 파일명 : marathon_crawler.py
# 위치   : src/data/collectors/marathon_crawler.py
# 역할   : 마라톤GO 목록 페이지 HTML에서 수도권 대회 파싱
# ================================================================

import requests
from bs4 import BeautifulSoup
from datetime import datetime, date
import re

METRO_KEYWORDS = ["서울", "경기", "인천"]


def fetch_marathon_events(region: str = "서울") -> list[dict]:
    url = "https://marathongo.co.kr/raceSchedule/domestic"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        res = requests.get(url, headers=headers, timeout=5)
        res.encoding = 'utf-8'
        res.raise_for_status()
    except Exception as e:
        print(f"[marathon_crawler] 요청 실패: {e}")
        return []

    soup = BeautifulSoup(res.content, 'html.parser', from_encoding='utf-8')
    events = []
    seen = set()

    for link in soup.find_all("a", href=re.compile(r"/raceDetail/domestic/")):
        text = link.get_text(separator=" ", strip=True)

        # 지역 필터링
        if region not in text:
            continue

        # 날짜 추출 ("5월 16일" 형태)
        date_match = re.search(r"(\d+)월\s*(\d+)일", text)
        if not date_match:
            continue

        month = int(date_match.group(1))
        day   = int(date_match.group(2))
        year  = datetime.now().year
        try:
            event_date = date(year, month, day)
            if event_date < date.today():
                event_date = date(year + 1, month, day)
        except ValueError:
            continue

        # 대회명 추출
        # 링크 href에서 slug 가져오기
        slug = link["href"].split("/")[-1]
        # 텍스트에서 대회명 찾기 (날짜/지역/거리/접수 제거)
        name = _clean_name(text, region)
        if not name:
            continue

        # 중복 제거
        key = (name, event_date)
        if key in seen:
            continue
        seen.add(key)

        # 장소 추출 (지역명 + | 이후)
        place_match = re.search(rf"{region}\s*\|\s*([^|]+)", text)
        location = place_match.group(1).strip() if place_match else region

        events.append({
            "name":     name,
            "date":     event_date,
            "location": f"{region} · {location}",
            "emoji":    "🏅",
        })

    return sorted(events, key=lambda x: x["date"])


def _clean_name(text: str, region: str) -> str | None:
    """텍스트에서 대회명만 추출"""
    remove_patterns = [
        r"\d+월\s*\d+일\s*\([가-힣]\)",   # 날짜 "5월 16일 (토)"
        r"\d+월\s*\d+일",                  # 날짜 "5월 16일"
        r"풀|하프|\d+\.?\d*km|\d+\.?\d*K", # 거리
        r"(?<!\S)(서울|경기|인천|대전|부산|대구|광주|경남|경북|전남|전북|충남|충북|강원|제주)(?!\S)",
        r"접수전|접수중|접수마감|정원\s*마감",
        r"\d{4}\.\d{2}\.\d{2}",
        r"\d+:\d+",
        r"집결|출발",
        r"2026|2025",
        r"\|.*",                           # 파이프 이후 전부 제거
        r"~.*",                            # ~ 이후 전부 제거
    ]
    cleaned = text
    for pattern in remove_patterns:
        cleaned = re.sub(pattern, " ", cleaned)

    words = [w.strip() for w in cleaned.split() if len(w.strip()) > 1]
    name = " ".join(words[:6]).strip()

    return name if len(name) > 2 else None