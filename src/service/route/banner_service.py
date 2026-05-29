from src.infrastructure.external.client.marathon_client import MarathonClient
from src.infrastructure.external.schema.marathon_schema import MarathonEvent
from src.infrastructure.external.schema.weather_schema import EnvironmentInfo
from datetime import datetime, date
import asyncio
import re


class BannerService:

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

    def __init__(self, marathon_client: MarathonClient):
        """
        BannerService 초기화
        """
        self.marathon_client = marathon_client

    # ── 이벤트 관련 메서드 ─────────────────────────────────────

    async def _fetch_all_events(self) -> list[dict]:
        """
        서울/경기/인천 이벤트를 병렬로 조회
        """
        results = await asyncio.gather(
            self.marathon_client.get_events("서울"),
            self.marathon_client.get_events("경기"),
            self.marathon_client.get_events("인천"),
        )
        return [event for region_events in results for event in region_events]

    def get_events(self) -> list[MarathonEvent]:
        """
        이벤트 목록을 조회합니다.
        """
        return asyncio.run(self._fetch_all_events())

    def get_active_event(self) -> dict | None:
        """
        D-14 이내 이벤트 반환
        """
        today = date.today()
        for event in self.get_events():
            diff = (event.date - today).days
            if -1 <= diff <= 14:
                return {**event.model_dump(), "diff": diff}
        return None

    def _get_event_text(self, event: dict) -> dict:
        """
        이벤트 정보를 배너 텍스트 형식으로 변환합니다.
        """
        diff       = event["diff"]
        name       = event["name"]
        loc        = event["location"]
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
            "emoji":    "🏅",
            "text":     text,
            "sub":      sub,
            "is_event": True,
            "date":     str(event_date),
            "location": loc,
            "url": f"https://marathongo.co.kr/raceDetail/domestic/{event.get('slug', '')}"
        }

    # ── 날씨 헬퍼 메서드 ───────────────────────────────────────

    def _is_hot(self, weather_msg: str) -> bool:
        """
        weather_msg에서 기온을 파싱해 23도 이상이면 True 반환
        """
        match = re.search(r"[-+]?\d+(\.\d+)?", weather_msg)
        if match:
            try:
                return float(match.group()) >= 23
            except ValueError:
                pass
        return False

    def _is_humid(self, weather_status: str) -> bool:
        """
        날씨 상태에 흐림/습함 관련 키워드가 있으면 True 반환
        """
        keywords = ["흐림", "구름", "습", "비"]
        return any(k in weather_status for k in keywords)

    # ── 메인 메서드 ────────────────────────────────────────────

    def get_banner(self, weather: EnvironmentInfo, hour: int | None = None) -> dict:
        """
        단일 배너 반환 (하위 호환용)
        """
        banners = self.get_banner_list(weather, hour)
        return banners[0] if banners else self.BANNERS["fixed"]["healing"]

    def get_banner_list(self, weather: EnvironmentInfo, hour: int | None = None) -> list:
        """
        홈 화면에 노출할 배너 목록 전체를 반환합니다.
        우선순위: 이벤트 → 시즌 → 고정
        """
        if hour is None:
            hour = datetime.now().hour

        status  = weather.weather_status
        msg     = weather.weather_msg
        banners = []

        # 1순위: 이벤트 배너
        active_event = self.get_active_event()
        if active_event:
            banners.append(self._get_event_text(active_event))

        # 2순위: 시즌 배너 (날씨 기반)
        if self._is_hot(msg):
            if 6 <= hour < 9:
                banners.append(self.BANNERS["season"]["hot_morning"])
            elif self._is_humid(status):
                banners.append(self.BANNERS["season"]["hot_humid"])
            else:
                banners.append(self.BANNERS["season"]["hot_sunny"])

        # 3순위: 고정 배너 (시간대 기반 전체 추가)
        if hour < 17:
            keys = ["dog", "healing"]
        elif hour < 21:
            keys = ["dog", "healing", "night"]
        else:
            keys = ["night"]

        for key in keys:
            banners.append(self.BANNERS["fixed"][key])

        return banners
