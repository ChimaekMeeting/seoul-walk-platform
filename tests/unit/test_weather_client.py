import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


# tests/conftest.py가 일반 테스트의 외부 호출 차단을 위해 weather_client 모듈 전체를
# MagicMock으로 선점한다. 이 파일은 해당 client 자체를 검증하므로 소스 모듈만 별칭으로 로드한다.
_MODULE_PATH = Path(__file__).parents[2] / "src/infrastructure/external/client/weather_client.py"
_SPEC = importlib.util.spec_from_file_location("weather_client_under_test", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_WEATHER_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_WEATHER_MODULE)
WeatherClient = _WEATHER_MODULE.WeatherClient


class _KakaoStub:
    async def get_address_from_coords(self, lat: float, lon: float):
        return SimpleNamespace(place_address="서울특별시 관악구 신림동")


def _response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    return response


def test_weather_request_uses_weather_service_key():
    client = WeatherClient(
        _KakaoStub(),
        weather_api_key="weather-service-key",
        air_korea_api_key="air-service-key",
    )
    response = _response(
        {
            "response": {
                "body": {
                    "items": {
                        "item": [
                            {"category": "PTY", "obsrValue": "0"},
                            {"category": "T1H", "obsrValue": "21.5"},
                        ]
                    }
                }
            }
        }
    )

    with patch.object(
        _WEATHER_MODULE.httpx.AsyncClient,
        "get",
        new=AsyncMock(return_value=response),
    ) as request:
        result = asyncio.run(client.get_weather(37.4666809, 126.9427169))

    assert request.await_args.kwargs["params"]["serviceKey"] == "weather-service-key"
    response.raise_for_status.assert_called_once_with()
    assert result == {"precipitation_type": "없음", "temperature": "21.5℃"}


def test_air_quality_request_uses_air_korea_service_key():
    client = WeatherClient(
        _KakaoStub(),
        weather_api_key="weather-service-key",
        air_korea_api_key="air-service-key",
    )
    response = _response(
        {
            "response": {
                "body": {
                    "items": [
                        {"khaiValue": "58", "pm10Value": "29", "pm25Value": "12"}
                    ]
                }
            }
        }
    )

    with patch.object(
        _WEATHER_MODULE.httpx.AsyncClient,
        "get",
        new=AsyncMock(return_value=response),
    ) as request:
        result = asyncio.run(client.get_air_quality(37.4666809, 126.9427169))

    assert request.await_args.kwargs["params"]["serviceKey"] == "air-service-key"
    assert request.await_args.kwargs["params"]["stationName"] == "관악구"
    response.raise_for_status.assert_called_once_with()
    assert result == {
        "air_quality_index": "58",
        "pm10": "29㎍/㎥",
        "pm25": "12㎍/㎥",
    }


def test_http_error_returns_none_without_exposing_request_url():
    client = WeatherClient(
        _KakaoStub(),
        weather_api_key="weather-service-key",
        air_korea_api_key="air-service-key",
    )
    response = MagicMock()
    response.raise_for_status.side_effect = RuntimeError("request failed")

    with patch.object(
        _WEATHER_MODULE.httpx.AsyncClient,
        "get",
        new=AsyncMock(return_value=response),
    ):
        result = asyncio.run(client.get_weather(37.4666809, 126.9427169))

    assert result is None
