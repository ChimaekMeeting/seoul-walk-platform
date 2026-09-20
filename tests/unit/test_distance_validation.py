"""목표 거리 공용 검증과 요청 스키마의 입력 계약 회귀 테스트."""

import math

import pytest
from pydantic import ValidationError

from src.interfaces.schema.walk_schema import WalkRouteRequest
from src.interfaces.validators.dist_validator import validate_target_km_positive
from src.schema.prewalk_schema import (
    CircularPreference,
    GPSArtPreference,
    OnewayPreference,
    WaypointLegPreference,
)


_ORIGIN = {"lat": 37.5, "lon": 127.0}


@pytest.mark.parametrize("value", [3, 3.5, "3", "3.5", 10])
def test_직접_경로는_정상_거리와_숫자_문자열을_허용한다(value):
    request = WalkRouteRequest(
        origin=_ORIGIN,
        mode="circular_random",
        target_km=value,
    )
    assert request.target_km == pytest.approx(float(value))


@pytest.mark.parametrize(
    "value",
    [
        0,
        -1,
        11,
        "0",
        "-1",
        "11",
        math.nan,
        math.inf,
        -math.inf,
        "NaN",
        "Infinity",
        "-Infinity",
        "",
        "not-a-number",
        True,
        False,
    ],
)
def test_직접_경로는_범위밖_비유한_비숫자_boolean_거리를_거절한다(value):
    with pytest.raises(ValidationError):
        WalkRouteRequest(
            origin=_ORIGIN,
            mode="circular_random",
            target_km=value,
        )


def test_직접_경로의_생략과_편도우회_필수_정책을_유지한다():
    circular = WalkRouteRequest(origin=_ORIGIN, mode="circular_random")
    assert circular.target_km is None

    with pytest.raises(ValidationError, match="목표 산책 거리"):
        WalkRouteRequest(
            origin=_ORIGIN,
            destination={"lat": 37.51, "lon": 127.01},
            mode="oneway_random",
        )

    with pytest.raises(ValidationError, match="도착지"):
        WalkRouteRequest(
            origin=_ORIGIN,
            mode="oneway_random",
            target_km=3,
        )


def test_편도우회의_기존_직선거리_검증을_유지한다():
    with pytest.raises(ValidationError, match="직선거리보다 짧습니다"):
        WalkRouteRequest(
            origin=_ORIGIN,
            destination={"lat": 37.51, "lon": 127.01},
            mode="oneway_random",
            target_km=1,
        )

    with pytest.raises(ValidationError, match="목적지가 목표 거리에 비해 너무 가깝습니다"):
        WalkRouteRequest(
            origin=_ORIGIN,
            destination={"lat": 37.5001, "lon": 127.0001},
            mode="oneway_random",
            target_km=3,
        )


def test_직접_경로_OpenAPI_스키마에_거리_범위가_드러난다():
    target_schema = WalkRouteRequest.model_json_schema()["properties"]["target_km"]
    number_schema = next(item for item in target_schema["anyOf"] if item.get("type") == "number")
    assert number_schema["exclusiveMinimum"] == 0
    assert number_schema["maximum"] == 10


@pytest.mark.parametrize(
    "model",
    [CircularPreference, OnewayPreference, GPSArtPreference, WaypointLegPreference],
)
@pytest.mark.parametrize(
    "value",
    [
        0,
        -1,
        "0",
        "-1",
        math.nan,
        math.inf,
        -math.inf,
        "NaN",
        "Infinity",
        "-Infinity",
        True,
        False,
    ],
)
def test_챗봇_거리_모델은_공용_하한_유한성_boolean_검증을_사용한다(model, value):
    with pytest.raises(ValidationError):
        model(target_km=value)


@pytest.mark.parametrize(
    "model",
    [CircularPreference, OnewayPreference, GPSArtPreference, WaypointLegPreference],
)
def test_챗봇_거리_모델은_숫자_문자열과_None을_기존처럼_허용한다(model):
    assert model(target_km="3.5").target_km == pytest.approx(3.5)
    assert model(target_km=None).target_km is None
    assert model().target_km is None


def test_공용_하한_검증은_10km_상한을_챗봇에_적용하지_않는다():
    assert validate_target_km_positive("11") == pytest.approx(11.0)
    assert CircularPreference(target_km="11").target_km == pytest.approx(11.0)
