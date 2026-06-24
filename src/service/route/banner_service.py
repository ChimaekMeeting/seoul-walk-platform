import logging
import re
from datetime import datetime, date

from src.infrastructure.external.client.marathon_client import MarathonClient
from src.infrastructure.external.client.weather_client import WeatherClient
from src.infrastructure.external.schema.marathon_schema import MarathonEvent
from src.repository.banner.banner_repository import BannerRepository
from src.interfaces.schema.banner_schema import BannerResponse, BannerStatus

logger = logging.getLogger(__name__)


class BannerService:

    def __init__(self, marathon_client: MarathonClient, weather_client: WeatherClient):
        self.marathon_client = marathon_client
        self.weather_client  = weather_client

    # ── 이벤트 관련 메서드 ─────────────────────────────────────

    async def _fetch_all_events(self) -> list[MarathonEvent]:
        return await self.marathon_client.get_events("서울")

    async def get_active_event(self) -> dict | None:
        today = date.today()
        for event in await self._fetch_all_events():
            diff = (event.date - today).days
            if -1 <= diff <= 14:
                return {**event.model_dump(), "diff": diff}
        return None

    def _get_event_text(self, event: dict) -> dict:
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

    def _is_hot(self, weather: dict) -> bool:
        temp_str = weather.get("기온", "")
        match = re.search(r"[-+]?\d+(\.\d+)?", temp_str)
        if match:
            try:
                return float(match.group()) >= 23
            except ValueError:
                pass
        return False

    def _is_humid(self, weather: dict) -> bool:
        status   = weather.get("강수형태", "")
        keywords = ["흐림", "구름", "습", "비"]
        return any(k in status for k in keywords)

    # ── 메인 메서드 ────────────────────────────────────────────

    async def get_banner_list(self, lat: float, lon: float, hour: int | None = None) -> BannerResponse:
        if hour is None:
            hour = datetime.now().hour

        try:
            weather = await self.weather_client.get_weather(lat, lon) or {}
        except Exception:
            logger.exception("weather_api_error | lat=%s | lon=%s", lat, lon)
            weather = {}

        try:
            banners = {b.key: b for b in BannerRepository.find_all()}
        except Exception:
            logger.exception("banner_db_error | lat=%s | lon=%s", lat, lon)
            return BannerResponse(status=BannerStatus.DB_ERROR, items=[])

        result = []

        # 1순위: 이벤트 배너
        try:
            active_event = await self.get_active_event()
            if active_event:
                result.append(self._get_event_text(active_event))
        except Exception:
            logger.exception("marathon_api_error | lat=%s | lon=%s", lat, lon)

        # 2순위: 시즌 배너 (날씨 기반)
        if self._is_hot(weather):
            if 6 <= hour < 9:
                key = "hot_morning"
            elif self._is_humid(weather):
                key = "hot_humid"
            else:
                key = "hot_sunny"
            if key in banners:
                result.append(banners[key].to_dict())

        # 3순위: 고정 배너 (시간대 기반)
        if hour < 17:
            fixed_keys = ["dog", "healing"]
        elif hour < 21:
            fixed_keys = ["dog", "healing", "night"]
        else:
            fixed_keys = ["night"]

        for key in fixed_keys:
            if key in banners:
                result.append(banners[key].to_dict())

        logger.info("banner_served | lat=%s | lon=%s | count=%d", lat, lon, len(result))
        return BannerResponse(status=BannerStatus.SUCCESS, items=result)
