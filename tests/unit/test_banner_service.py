"""
tests/unit/test_banner_service.py
BannerService 단위 테스트

담당: QA (예원)
검증 항목:
  - _is_hot        : 기온 파싱 및 23도 기준 판단
  - _is_humid      : 날씨 상태 키워드 감지
  - get_banner_list: 이벤트 > 시즌 > 고정 우선순위 및 시간대별 구성
  - _get_event_text: D-0 / D-3 이내 / D-14 이내 텍스트 분기
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import date

from src.service.route.banner_service import BannerService

# ── 공통 픽스처 ──────────────────────────────────────────────────────────────


@pytest.fixture
def service():
    mock_client = MagicMock()
    mock_client.get_events = MagicMock(return_value=[])
    svc = BannerService(marathon_client=mock_client)
    # 이벤트 없음으로 고정 (각 테스트에서 필요시 override)
    svc.get_active_event = MagicMock(return_value=None)
    return svc


def make_weather(status="맑음", msg="현재 기온은 20도입니다"):
    """테스트용 EnvironmentInfo mock 생성."""
    weather = MagicMock()
    weather.weather_status = status
    weather.weather_msg = msg
    return weather


# ── _is_hot ──────────────────────────────────────────────────────────────────


class TestIsHot:
    def test_23도_이상이면_True다(self, service):
        assert service._is_hot("현재 기온은 23도입니다") is True

    def test_30도이면_True다(self, service):
        assert service._is_hot("30도로 매우 덥습니다") is True

    def test_22도이면_False다(self, service):
        assert service._is_hot("현재 기온은 22도입니다") is False

    def test_0도이면_False다(self, service):
        assert service._is_hot("0도의 추운 날씨") is False

    def test_숫자_없으면_False다(self, service):
        assert service._is_hot("기온 정보 없음") is False

    def test_소수점_기온도_처리한다(self, service):
        assert service._is_hot("기온 23.5도") is True
        assert service._is_hot("기온 22.9도") is False

    def test_음수_기온은_False다(self, service):
        assert service._is_hot("영하 -5도") is False


# ── _is_humid ─────────────────────────────────────────────────────────────────


class TestIsHumid:
    @pytest.mark.parametrize(
        "status", ["흐림", "구름 많음", "습한 날씨", "비가 내립니다"]
    )
    def test_습한_키워드가_있으면_True다(self, service, status):
        assert service._is_humid(status) is True

    @pytest.mark.parametrize("status", ["맑음", "화창", "바람 강함"])
    def test_관련_키워드_없으면_False다(self, service, status):
        assert service._is_humid(status) is False

    def test_빈_문자열은_False다(self, service):
        assert service._is_humid("") is False


# ── get_banner_list 우선순위 ──────────────────────────────────────────────────


class TestGetBannerListPriority:
    def test_이벤트_있으면_첫_번째_배너가_이벤트다(self, service):
        service.get_active_event = MagicMock(
            return_value={
                "name": "서울마라톤",
                "location": "여의도",
                "date": date.today(),
                "diff": 3,
                "slug": "seoul-marathon",
            }
        )
        weather = make_weather()
        banners = service.get_banner_list(weather, hour=10)
        assert banners[0].get("is_event") is True

    def test_이벤트_없으면_이벤트_배너_없다(self, service):
        weather = make_weather()
        banners = service.get_banner_list(weather, hour=10)
        assert all(not b.get("is_event") for b in banners)

    def test_더운_날씨에_시즌_배너가_포함된다(self, service):
        weather = make_weather(status="맑음", msg="기온 30도로 매우 덥습니다")
        banners = service.get_banner_list(weather, hour=12)
        texts = [b["text"] for b in banners]
        assert any("덥" in t or "그늘" in t or "숲길" in t for t in texts)

    def test_시원한_날씨에_시즌_배너_없다(self, service):
        weather = make_weather(status="맑음", msg="기온 18도의 선선한 날씨")
        banners = service.get_banner_list(weather, hour=12)
        season_keys = ["hot_sunny", "hot_humid", "hot_morning"]
        season_texts = [BannerService.BANNERS["season"][k]["text"] for k in season_keys]
        assert all(b["text"] not in season_texts for b in banners)


# ── get_banner_list 시간대별 고정 배너 ────────────────────────────────────────


class TestGetBannerListByHour:
    def test_오전에는_night_배너_없다(self, service):
        weather = make_weather()
        banners = service.get_banner_list(weather, hour=10)
        texts = [b["text"] for b in banners]
        assert BannerService.BANNERS["fixed"]["night"]["text"] not in texts

    def test_저녁에는_night_배너_포함된다(self, service):
        weather = make_weather()
        banners = service.get_banner_list(weather, hour=19)
        texts = [b["text"] for b in banners]
        assert BannerService.BANNERS["fixed"]["night"]["text"] in texts

    def test_야간에는_night_배너만_고정된다(self, service):
        weather = make_weather()
        banners = service.get_banner_list(weather, hour=22)
        fixed_texts = [b["text"] for b in banners if not b.get("is_event")]
        assert BannerService.BANNERS["fixed"]["night"]["text"] in fixed_texts
        assert BannerService.BANNERS["fixed"]["dog"]["text"] not in fixed_texts

    def test_새벽_6시_더운_날씨에_hot_morning_배너_나온다(self, service):
        weather = make_weather(msg="기온 25도로 더운 아침")
        banners = service.get_banner_list(weather, hour=7)
        texts = [b["text"] for b in banners]
        assert BannerService.BANNERS["season"]["hot_morning"]["text"] in texts

    def test_더운_습한_날씨에_hot_humid_배너_나온다(self, service):
        weather = make_weather(status="흐림", msg="기온 28도로 습합니다")
        banners = service.get_banner_list(weather, hour=14)
        texts = [b["text"] for b in banners]
        assert BannerService.BANNERS["season"]["hot_humid"]["text"] in texts

    def test_더운_맑은_날씨에_hot_sunny_배너_나온다(self, service):
        weather = make_weather(status="맑음", msg="기온 28도로 맑습니다")
        banners = service.get_banner_list(weather, hour=14)
        texts = [b["text"] for b in banners]
        assert BannerService.BANNERS["season"]["hot_sunny"]["text"] in texts


# ── _get_event_text ───────────────────────────────────────────────────────────


class TestGetEventText:
    def test_D0이면_오늘_대회날_텍스트다(self, service):
        event = {
            "diff": 0,
            "name": "서울마라톤",
            "location": "여의도",
            "date": date.today(),
            "slug": "seoul",
        }
        result = service._get_event_text(event)
        assert "오늘" in result["text"]
        assert result["emoji"] == "🏅"
        assert result["is_event"] is True

    def test_D3이내면_이번_주말_텍스트다(self, service):
        event = {
            "diff": 2,
            "name": "한강마라톤",
            "location": "한강공원",
            "date": date.today(),
            "slug": "hangang",
        }
        result = service._get_event_text(event)
        assert "이번 주말" in result["text"]
        assert "D-2" in result["sub"]

    def test_D14이내면_미리_준비_텍스트다(self, service):
        event = {
            "diff": 10,
            "name": "수원마라톤",
            "location": "수원",
            "date": date.today(),
            "slug": "suwon",
        }
        result = service._get_event_text(event)
        assert "미리" in result["text"]
        assert "D-10" in result["sub"]

    def test_url에_slug가_포함된다(self, service):
        event = {
            "diff": 5,
            "name": "테스트대회",
            "location": "서울",
            "date": date.today(),
            "slug": "test-race",
        }
        result = service._get_event_text(event)
        assert "test-race" in result["url"]

    def test_반환_구조에_필수_키가_있다(self, service):
        event = {
            "diff": 1,
            "name": "대회",
            "location": "서울",
            "date": date.today(),
            "slug": "race",
        }
        result = service._get_event_text(event)
        for key in ["emoji", "text", "sub", "is_event", "date", "location", "url"]:
            assert key in result
