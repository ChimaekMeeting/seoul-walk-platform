"""
tests/unit/test_banner_service.py
BannerService 단위 테스트

검증 항목:
  - _is_hot        : 기온 파싱 및 23도 기준 판단
  - _is_humid      : 날씨 상태 키워드 감지
  - get_banner_list: 이벤트 > 시즌 > 고정 우선순위 및 시간대별 구성
  - get_banner_list: 예외처리 (날씨 API 실패 / 마라톤 API 실패 / DB 실패)
  - _get_event_text: D-0 / D-3 이내 / D-14 이내 텍스트 분기
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date

from src.service.route.banner_service import BannerService
from src.interfaces.schema.banner_schema import BannerStatus

LAT, LON = 37.5, 126.9


# ── 공통 픽스처 ──────────────────────────────────────────────────────────────


def make_service(
    weather_result: dict | None = None,
    events_result: list | None = None,
    db_banners: list | None = None,
) -> BannerService:
    """
    외부 의존성을 모두 mock으로 교체한 BannerService를 반환합니다.
    - weather_result : weather_client.get_weather() 반환값 (기본: 빈 dict)
    - events_result  : marathon_client.get_events() 반환값 (기본: 빈 리스트)
    - db_banners     : BannerRepository.find_all() 반환값 (기본: 빈 리스트)
    """
    marathon_mock = MagicMock()
    marathon_mock.get_events = AsyncMock(return_value=events_result or [])

    weather_mock = MagicMock()
    weather_mock.get_weather = AsyncMock(return_value=weather_result or {})

    svc = BannerService(marathon_client=marathon_mock, weather_client=weather_mock)
    svc._db_banners = db_banners or []
    return svc


def make_db_banner(key: str, emoji: str, text: str, sub: str) -> MagicMock:
    """Banner 엔티티 mock을 생성합니다."""
    b = MagicMock()
    b.key = key
    b.to_dict.return_value = {"key": key, "emoji": emoji, "text": text, "sub": sub, "scoring": {}}
    return b


def make_all_db_banners() -> list:
    return [
        make_db_banner("hot_sunny",  "🌳", "오늘 덥죠? 그늘 가득한 숲길 어떠세요?", "더위를 피하는 나만의 산책 코스"),
        make_db_banner("hot_humid",  "🌊", "습한 날엔 물가 바람이 최고예요",       "시원한 물가 코스 추천"),
        make_db_banner("hot_morning","🌅", "더워지기 전에 먼저 걸어볼까요?",        "상쾌한 새벽 산책 코스"),
        make_db_banner("dog",        "🐶", "강아지랑 함께 걷기 좋은 길이에요",      "반려견 동반 가능 코스"),
        make_db_banner("healing",    "🌿", "조용하게 걷고 싶을 때 추천해요",        "힐링 숲길 코스"),
        make_db_banner("night",      "🌃", "저녁에 걷기 좋은 야경 코스예요",        "야경 명소 산책로"),
    ]


# ── _is_hot ──────────────────────────────────────────────────────────────────


class TestIsHot:
    @pytest.fixture
    def svc(self):
        return make_service()

    def test_23도_이상이면_True다(self, svc):
        assert svc._is_hot({"기온": "현재 기온은 23도입니다"}) is True

    def test_30도이면_True다(self, svc):
        assert svc._is_hot({"기온": "30도로 매우 덥습니다"}) is True

    def test_22도이면_False다(self, svc):
        assert svc._is_hot({"기온": "현재 기온은 22도입니다"}) is False

    def test_0도이면_False다(self, svc):
        assert svc._is_hot({"기온": "0도의 추운 날씨"}) is False

    def test_기온_키_없으면_False다(self, svc):
        assert svc._is_hot({}) is False

    def test_소수점_기온도_처리한다(self, svc):
        assert svc._is_hot({"기온": "기온 23.5도"}) is True
        assert svc._is_hot({"기온": "기온 22.9도"}) is False

    def test_음수_기온은_False다(self, svc):
        assert svc._is_hot({"기온": "영하 -5도"}) is False


# ── _is_humid ─────────────────────────────────────────────────────────────────


class TestIsHumid:
    @pytest.fixture
    def svc(self):
        return make_service()

    @pytest.mark.parametrize("status", ["흐림", "구름 많음", "습한 날씨", "비가 내립니다"])
    def test_습한_키워드가_있으면_True다(self, svc, status):
        assert svc._is_humid({"강수형태": status}) is True

    @pytest.mark.parametrize("status", ["맑음", "화창", "바람 강함"])
    def test_관련_키워드_없으면_False다(self, svc, status):
        assert svc._is_humid({"강수형태": status}) is False

    def test_강수형태_키_없으면_False다(self, svc):
        assert svc._is_humid({}) is False


# ── get_banner_list 우선순위 ──────────────────────────────────────────────────


class TestGetBannerListPriority:
    @pytest.mark.anyio
    async def test_이벤트_있으면_첫_번째_배너가_이벤트다(self):
        from src.infrastructure.external.schema.marathon_schema import MarathonEvent
        event = MarathonEvent(name="서울마라톤", location="여의도", date=date.today(), slug="seoul")

        svc = make_service(events_result=[event], db_banners=make_all_db_banners())
        with patch("src.service.route.banner_service.BannerRepository.find_all", return_value=svc._db_banners):
            resp = await svc.get_banner_list(LAT, LON, hour=10)

        assert resp.status == BannerStatus.SUCCESS
        assert resp.items[0].is_event is True

    @pytest.mark.anyio
    async def test_이벤트_없으면_이벤트_배너_없다(self):
        svc = make_service(db_banners=make_all_db_banners())
        with patch("src.service.route.banner_service.BannerRepository.find_all", return_value=svc._db_banners):
            resp = await svc.get_banner_list(LAT, LON, hour=10)

        assert all(not item.is_event for item in resp.items)

    @pytest.mark.anyio
    async def test_더운_날씨에_시즌_배너가_포함된다(self):
        svc = make_service(
            weather_result={"기온": "30도로 매우 덥습니다", "강수형태": "맑음"},
            db_banners=make_all_db_banners(),
        )
        with patch("src.service.route.banner_service.BannerRepository.find_all", return_value=svc._db_banners):
            resp = await svc.get_banner_list(LAT, LON, hour=12)

        texts = [item.text for item in resp.items]
        assert any("덥" in t or "그늘" in t or "숲길" in t for t in texts)

    @pytest.mark.anyio
    async def test_시원한_날씨에_시즌_배너_없다(self):
        svc = make_service(
            weather_result={"기온": "18도의 선선한 날씨", "강수형태": "맑음"},
            db_banners=make_all_db_banners(),
        )
        with patch("src.service.route.banner_service.BannerRepository.find_all", return_value=svc._db_banners):
            resp = await svc.get_banner_list(LAT, LON, hour=12)

        keys = [item.key for item in resp.items]
        assert "hot_sunny" not in keys
        assert "hot_humid" not in keys
        assert "hot_morning" not in keys


# ── get_banner_list 시간대별 고정 배너 ────────────────────────────────────────


class TestGetBannerListByHour:
    @pytest.mark.anyio
    async def test_오전에는_night_배너_없다(self):
        svc = make_service(db_banners=make_all_db_banners())
        with patch("src.service.route.banner_service.BannerRepository.find_all", return_value=svc._db_banners):
            resp = await svc.get_banner_list(LAT, LON, hour=10)

        assert all(item.key != "night" for item in resp.items)

    @pytest.mark.anyio
    async def test_저녁에는_night_배너_포함된다(self):
        svc = make_service(db_banners=make_all_db_banners())
        with patch("src.service.route.banner_service.BannerRepository.find_all", return_value=svc._db_banners):
            resp = await svc.get_banner_list(LAT, LON, hour=19)

        assert any(item.key == "night" for item in resp.items)

    @pytest.mark.anyio
    async def test_야간에는_dog_healing_배너_없다(self):
        svc = make_service(db_banners=make_all_db_banners())
        with patch("src.service.route.banner_service.BannerRepository.find_all", return_value=svc._db_banners):
            resp = await svc.get_banner_list(LAT, LON, hour=22)

        keys = [item.key for item in resp.items if not item.is_event]
        assert "dog" not in keys
        assert "healing" not in keys

    @pytest.mark.anyio
    async def test_새벽_6시_더운_날씨에_hot_morning_배너_나온다(self):
        svc = make_service(
            weather_result={"기온": "25도로 더운 아침", "강수형태": "맑음"},
            db_banners=make_all_db_banners(),
        )
        with patch("src.service.route.banner_service.BannerRepository.find_all", return_value=svc._db_banners):
            resp = await svc.get_banner_list(LAT, LON, hour=7)

        assert any(item.key == "hot_morning" for item in resp.items)

    @pytest.mark.anyio
    async def test_더운_습한_날씨에_hot_humid_배너_나온다(self):
        svc = make_service(
            weather_result={"기온": "28도로 습합니다", "강수형태": "흐림"},
            db_banners=make_all_db_banners(),
        )
        with patch("src.service.route.banner_service.BannerRepository.find_all", return_value=svc._db_banners):
            resp = await svc.get_banner_list(LAT, LON, hour=14)

        assert any(item.key == "hot_humid" for item in resp.items)

    @pytest.mark.anyio
    async def test_더운_맑은_날씨에_hot_sunny_배너_나온다(self):
        svc = make_service(
            weather_result={"기온": "28도로 맑습니다", "강수형태": "맑음"},
            db_banners=make_all_db_banners(),
        )
        with patch("src.service.route.banner_service.BannerRepository.find_all", return_value=svc._db_banners):
            resp = await svc.get_banner_list(LAT, LON, hour=14)

        assert any(item.key == "hot_sunny" for item in resp.items)


# ── 예외처리 ──────────────────────────────────────────────────────────────────


class TestGetBannerListExceptionHandling:
    @pytest.mark.anyio
    async def test_날씨_API_실패해도_고정_배너는_반환된다(self):
        svc = make_service(db_banners=make_all_db_banners())
        svc.weather_client.get_weather = AsyncMock(side_effect=Exception("날씨 API 오류"))

        with patch("src.service.route.banner_service.BannerRepository.find_all", return_value=svc._db_banners):
            resp = await svc.get_banner_list(LAT, LON, hour=10)

        assert resp.status == BannerStatus.SUCCESS
        assert len(resp.items) > 0

    @pytest.mark.anyio
    async def test_마라톤_API_실패해도_나머지_배너는_반환된다(self):
        svc = make_service(db_banners=make_all_db_banners())
        svc.marathon_client.get_events = AsyncMock(side_effect=Exception("마라톤 API 오류"))

        with patch("src.service.route.banner_service.BannerRepository.find_all", return_value=svc._db_banners):
            resp = await svc.get_banner_list(LAT, LON, hour=10)

        assert resp.status == BannerStatus.SUCCESS
        assert all(not item.is_event for item in resp.items)

    @pytest.mark.anyio
    async def test_DB_실패하면_DB_ERROR_상태로_빈_목록_반환된다(self):
        svc = make_service()

        with patch("src.service.route.banner_service.BannerRepository.find_all", side_effect=Exception("DB 연결 오류")):
            resp = await svc.get_banner_list(LAT, LON, hour=10)

        assert resp.status == BannerStatus.DB_ERROR
        assert resp.items == []

    @pytest.mark.anyio
    async def test_날씨_및_마라톤_모두_실패해도_고정_배너는_반환된다(self):
        svc = make_service(db_banners=make_all_db_banners())
        svc.weather_client.get_weather = AsyncMock(side_effect=Exception("날씨 API 오류"))
        svc.marathon_client.get_events = AsyncMock(side_effect=Exception("마라톤 API 오류"))

        with patch("src.service.route.banner_service.BannerRepository.find_all", return_value=svc._db_banners):
            resp = await svc.get_banner_list(LAT, LON, hour=10)

        assert resp.status == BannerStatus.SUCCESS
        assert len(resp.items) > 0


# ── _get_event_text ───────────────────────────────────────────────────────────


class TestGetEventText:
    @pytest.fixture
    def svc(self):
        return make_service()

    def test_D0이면_오늘_대회날_텍스트다(self, svc):
        event = {"diff": 0, "name": "서울마라톤", "location": "여의도", "date": date.today(), "slug": "seoul"}
        result = svc._get_event_text(event)
        assert "오늘" in result["text"]
        assert result["emoji"] == "🏅"
        assert result["is_event"] is True

    def test_D3이내면_이번_주말_텍스트다(self, svc):
        event = {"diff": 2, "name": "한강마라톤", "location": "한강공원", "date": date.today(), "slug": "hangang"}
        result = svc._get_event_text(event)
        assert "이번 주말" in result["text"]
        assert "D-2" in result["sub"]

    def test_D14이내면_미리_준비_텍스트다(self, svc):
        event = {"diff": 10, "name": "수원마라톤", "location": "수원", "date": date.today(), "slug": "suwon"}
        result = svc._get_event_text(event)
        assert "미리" in result["text"]
        assert "D-10" in result["sub"]

    def test_url에_slug가_포함된다(self, svc):
        event = {"diff": 5, "name": "테스트대회", "location": "서울", "date": date.today(), "slug": "test-race"}
        result = svc._get_event_text(event)
        assert "test-race" in result["url"]

    def test_반환_구조에_필수_키가_있다(self, svc):
        event = {"diff": 1, "name": "대회", "location": "서울", "date": date.today(), "slug": "race"}
        result = svc._get_event_text(event)
        for key in ["emoji", "text", "sub", "is_event", "date", "location", "url"]:
            assert key in result
