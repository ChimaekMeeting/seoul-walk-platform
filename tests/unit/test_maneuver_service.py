import importlib
import sys

import pytest

from src.interfaces.schema.walk_schema import (
    WalkMode,
    WalkRouteResponse,
    WalkRouteStatus,
)
from src.service.route.maneuver_service import build_maneuvers


def test_build_maneuvers_preserves_start_turn_and_arrival():
    coordinates = [
        [37.5665, 126.9780],
        [37.5665, 126.9880],
        [37.5765, 126.9880],
    ]

    maneuvers = build_maneuvers(coordinates, node_ids=[10, 11, 12])

    assert [item.type.value for item in maneuvers] == ["start", "left", "arrive"]
    assert [item.node_id for item in maneuvers] == [10, 11, 12]
    assert maneuvers[0].distance_from_start_m == pytest.approx(0.0)
    assert maneuvers[1].distance_from_start_m > 0.0
    assert maneuvers[2].distance_from_start_m > maneuvers[1].distance_from_start_m


def test_build_maneuvers_calculates_turn_angle_and_bearings():
    coordinates = [
        [37.5665, 126.9780],
        [37.5765, 126.9780],
        [37.5765, 126.9880],
    ]

    turn = build_maneuvers(coordinates)[1]

    assert turn.bearing_before_deg == pytest.approx(0.0, abs=0.1)
    assert turn.bearing_after_deg == pytest.approx(90.0, abs=0.1)
    assert turn.turn_angle_deg == pytest.approx(90.0, abs=0.2)


def test_build_maneuvers_ignores_small_direction_changes():
    coordinates = [
        [37.5665, 126.9780],
        [37.5665, 126.9880],
        [37.5667, 126.9980],
    ]

    maneuvers = build_maneuvers(coordinates)

    assert [item.type.value for item in maneuvers] == ["start", "arrive"]


def test_build_maneuvers_handles_duplicate_coordinates():
    coordinates = [
        [37.5665, 126.9780],
        [37.5665, 126.9780],
        [37.5765, 126.9780],
    ]

    maneuvers = build_maneuvers(coordinates)

    assert maneuvers[0].bearing_after_deg is None
    assert maneuvers[-1].type.value == "arrive"


def test_walk_route_response_remains_backward_compatible():
    response = WalkRouteResponse(
        status=WalkRouteStatus.SUCCESS,
        mode=WalkMode.ONEWAY_SHORTEST,
        coordinates=[[37.5665, 126.9780]],
        total_km=0.0,
    )

    payload = response.model_dump(mode="json")

    assert payload["status"] == "success"
    assert payload["mode"] == "oneway_shortest"
    assert payload["coordinates"] == [[37.5665, 126.9780]]
    assert payload["maneuvers"] == []
    assert payload["node_ids"] == []


def test_maneuver_service_does_not_import_or_call_kakao(monkeypatch):
    kakao_modules = {
        name: module
        for name, module in sys.modules.items()
        if "kakao" in name.lower()
    }

    for name in kakao_modules:
        monkeypatch.delitem(sys.modules, name, raising=False)

    module = importlib.import_module("src.service.route.maneuver_service")
    module.build_maneuvers(
        [[37.5665, 126.9780], [37.5765, 126.9780]],
    )

    assert not any(
        "kakao" in name.lower()
        for name in sys.modules
        if name.startswith("src.service.route.maneuver_service")
    )
