import httpx
from bs4 import BeautifulSoup
from datetime import datetime, date
import re

from src.infrastructure.external.schema import MarathonEvent


class MarathonClient:
    def __init__(self):
        self.BASE_URL = "https://marathongo.co.kr/raceSchedule/domestic"
        self.HEADERS = {"User-Agent": "Mozilla/5.0"}

    async def get_events(self, region: str = "서울") -> list[MarathonEvent]:
        """
        전체 파이프라인 실행: 요청 → 파싱 → 필터 → 정렬
        """
        html = await self._fetch_html()
        if html is None:
            return []

        links = self._extract_links(html)
        events = []
        seen = set()

        for link_tag in links:
            text = link_tag.get_text(separator=" ", strip=True)
            if region not in text:
                continue

            event = self._build_event(link_tag, text, region)
            if event is None:
                continue

            key = (event.name, event.date)
            if key in seen:
                continue
            seen.add(key)

            events.append(event)

        return sorted(events, key=lambda x: x.date)

    async def _fetch_html(self) -> bytes | None:
        """
        HTTP 요청 후 응답 바이트 반환
        """
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(self.BASE_URL, headers=self.HEADERS, timeout=5)
                res.raise_for_status()
                return res.content
        except Exception as e:
            print(f"[marathon_client] 요청 실패: {e}")
            return None

    def _extract_links(self, html: bytes) -> list:
        """
        HTML에서 대회 상세 링크 태그 목록 반환
        """
        soup = BeautifulSoup(html, "html.parser", from_encoding="utf-8")
        return soup.find_all("a", href=re.compile(r"/raceDetail/domestic/"))

    def _build_event(self, link_tag, text: str, region: str) -> MarathonEvent | None:
        """
        링크 태그와 텍스트로부터 이벤트 딕셔너리 생성
        """
        event_date = self._parse_date(text)
        if event_date is None:
            return None

        name = self._clean_name(text, region)
        if not name:
            return None

        location = self._parse_location(text, region)
        slug = link_tag["href"].split("/")[-1]

        return MarathonEvent(
            name=name,
            date=event_date,
            location=f"{region} · {location}",
            slug=slug,
        )

    def _parse_date(self, text: str) -> date | None:
        """
        텍스트에서 날짜 추출 ('5월 16일' 형태)
        """
        match = re.search(r"(\d+)월\s*(\d+)일", text)
        if not match:
            return None

        month = int(match.group(1))
        day = int(match.group(2))
        year = datetime.now().year

        try:
            event_date = date(year, month, day)
            if event_date < date.today():
                event_date = date(year + 1, month, day)
            return event_date
        except ValueError:
            return None

    def _parse_location(self, text: str, region: str) -> str:
        """
        텍스트에서 장소 추출 (파이프 구분자 기준)
        """
        match = re.search(rf"{region}\s*\|\s*([^|]+)", text)
        return match.group(1).strip() if match else region

    def _clean_name(self, text: str, region: str) -> str | None:
        """
        텍스트에서 불필요한 정보를 제거하고 대회명만 반환
        """
        remove_patterns = [
            r"\d+월\s*\d+일\s*\([가-힣]\)",
            r"\d+월\s*\d+일",
            r"풀|하프|\d+\.?\d*km|\d+\.?\d*K",
            r"(?<!\S)(서울|경기|인천|대전|부산|대구|광주|경남|경북|전남|전북|충남|충북|강원|제주)(?!\S)",
            r"접수전|접수중|접수마감|정원\s*마감",
            r"\d{4}\.\d{2}\.\d{2}",
            r"\d+:\d+",
            r"집결|출발",
            r"2026|2025",
            r"\|.*",
            r"~.*",
        ]
        cleaned = text
        for pattern in remove_patterns:
            cleaned = re.sub(pattern, " ", cleaned)

        words = [w.strip() for w in cleaned.split() if len(w.strip()) > 1]
        name = " ".join(words[:6]).strip()

        return name if len(name) > 2 else None