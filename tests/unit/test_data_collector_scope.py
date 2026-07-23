from unittest.mock import MagicMock

import pytest

from src.data import data_collector
from src.data import source_collector


def collector_factory(name: str, calls: list[str]):
    instance = MagicMock()
    instance.upsert.side_effect = lambda: calls.append(f"{name}.upsert")
    instance.rebuild.side_effect = lambda: calls.append(f"{name}.rebuild")
    instance.save.side_effect = lambda: calls.append(f"{name}.save")
    instance.update_accident.side_effect = lambda: calls.append(
        f"{name}.update_accident"
    )
    instance.update_outdoor_exercise.side_effect = lambda: calls.append(
        f"{name}.update_outdoor_exercise"
    )
    return MagicMock(return_value=instance)


def test_v1_runs_only_network_boundary_and_water(monkeypatch):
    calls: list[str] = []
    collector_names = (
        "BaseNetworkCollector",
        "NatureCollector",
        "SafetyCollector",
        "ChildCollector",
        "SeoulBoundaryCollector",
        "SeoulWaterCollector",
        "ParkPolygonCollector",
        "LandmarkCollector",
        "RunningCourseCollector",
    )
    for name in collector_names:
        monkeypatch.setattr(
            data_collector,
            name,
            collector_factory(name, calls),
        )

    data_collector.collect(network_mode="upsert", scope="v1")

    assert calls == [
        "BaseNetworkCollector.upsert",
        "ParkPolygonCollector.save",
        "SeoulBoundaryCollector.save",
        "SeoulWaterCollector.save",
    ]


def test_legacy_all_keeps_existing_collectors(monkeypatch):
    calls: list[str] = []
    collector_names = (
        "BaseNetworkCollector",
        "NatureCollector",
        "SafetyCollector",
        "ChildCollector",
        "SeoulBoundaryCollector",
        "SeoulWaterCollector",
        "ParkPolygonCollector",
        "LandmarkCollector",
        "RunningCourseCollector",
    )
    for name in collector_names:
        monkeypatch.setattr(
            data_collector,
            name,
            collector_factory(name, calls),
        )

    data_collector.collect(network_mode="rebuild", scope="legacy-all")

    assert calls == [
        "BaseNetworkCollector.rebuild",
        "NatureCollector.save",
        "SafetyCollector.save",
        "ChildCollector.save",
        "SeoulBoundaryCollector.save",
        "SeoulWaterCollector.save",
        "LandmarkCollector.save",
        "SafetyCollector.update_accident",
        "RunningCourseCollector.update_outdoor_exercise",
    ]


def test_v1_source_scope_does_not_collect_external_raw(monkeypatch):
    for source_name in ("OSMSource", "KakaoSource", "PublicSource", "CSVSource"):
        source = MagicMock()
        monkeypatch.setattr(source_collector, source_name, source)

    source_collector.collect(scope="v1")

    source_collector.OSMSource.assert_not_called()
    source_collector.KakaoSource.assert_not_called()
    source_collector.PublicSource.assert_not_called()
    source_collector.CSVSource.assert_not_called()


@pytest.mark.parametrize(
    ("collector", "kwargs"),
    (
        (data_collector.collect, {"scope": "invalid"}),
        (source_collector.collect, {"scope": "invalid"}),
    ),
)
def test_unknown_scope_is_rejected(collector, kwargs):
    with pytest.raises(ValueError):
        collector(**kwargs)
