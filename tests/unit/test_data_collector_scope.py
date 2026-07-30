from unittest.mock import MagicMock
from types import SimpleNamespace

import pandas as pd
import pytest

from src.data import data_collector
from src.data import source_collector
from src.data.collectors.child_collector import ChildCollector
from src.data.collectors.safety_collector import SafetyCollector
from src.data.sources.csv_source import CSVSource


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


def test_toilet_source_corrects_two_seoul_facilities(monkeypatch):
    source = CSVSource()
    raw = pd.DataFrame(
        [
            {
                "연번": 266601,
                "건물명": "을지로3가파출소",
                "도로명주소": "대전광역시 중구 충무로 56-1",
                "지번주소": None,
                "x 좌표": 127.42379959,
                "y 좌표": 36.31764252,
                "구 명칭": "중구",
                "유형": "공공기관",
                "개방시간": "상시",
                "장애인화장실 현황": None,
                "편의시설 (기타설비)": None,
            },
            {
                "연번": 266704,
                "건물명": "충무로119안전센터",
                "도로명주소": "대전광역시 중구 충무로 11",
                "지번주소": None,
                "x 좌표": 127.41884512,
                "y 좌표": 36.31847845,
                "구 명칭": "중구",
                "유형": "공공기관",
                "개방시간": "상시",
                "장애인화장실 현황": None,
                "편의시설 (기타설비)": None,
            },
        ]
    )
    monkeypatch.setattr(source, "_read_csv", lambda _: raw.copy())

    df, lat_col, lon_col, name_col, addr_col, city_col, end_lat_col, end_lon_col = (
        source._load_toilet()
    )

    assert df["도로명주소"].tolist() == [
        "서울특별시 중구 충무로 56-1",
        "서울특별시 중구 충무로 11",
    ]
    assert df["x 좌표"].tolist() == [126.992848341729, 126.992912675198]
    assert df["y 좌표"].tolist() == [37.5661815238113, 37.5621562365797]
    assert (lat_col, lon_col, name_col, addr_col) == (
        "y 좌표",
        "x 좌표",
        "건물명",
        "도로명주소",
    )
    assert (city_col, end_lat_col, end_lon_col) == (None, None, None)


def test_clean_preserves_records_at_the_same_location():
    source = CSVSource()
    raw = pd.DataFrame(
        [
            {"위도": 37.5, "경도": 127.0, "시도명": "서울특별시", "센서종류": "전류센서"},
            {"위도": 37.5, "경도": 127.0, "시도명": "서울특별시", "센서종류": "속도센서"},
        ]
    )

    cleaned = source.clean(
        raw,
        lat_col="위도",
        lon_col="경도",
        city_col="시도명",
    )

    assert len(cleaned) == 2


def test_streetlight_layer_aggregates_records_at_the_same_location():
    collector = SafetyCollector()
    collector.csv = MagicMock()
    collector.csv.get.return_value = pd.DataFrame(
        [
            {"csv_raw_id": 1, "geom": SimpleNamespace(x=127.0, y=37.5)},
            {"csv_raw_id": 2, "geom": SimpleNamespace(x=127.0, y=37.5)},
            {"csv_raw_id": 3, "geom": SimpleNamespace(x=127.1, y=37.6)},
        ]
    )

    records = collector.build_streetlight_records()

    assert len(records) == 2
    assert {record["csv_raw_id"] for record in records} == {1, 3}


def test_protection_zone_uses_seoul_address_prefix(monkeypatch):
    source = CSVSource()
    raw = pd.DataFrame(
        [
            {
                "대상시설명": "서울시설",
                "소재지도로명주소": "서울특별시 강서구 수명로21길 88",
                "소재지지번주소": None,
                "위도": 37.55,
                "경도": 126.82,
                "제공기관명": "서울특별시 강서구",
            },
            {
                "대상시설명": "시흥시설",
                "소재지도로명주소": "경기도 시흥시 서울대학로 150-17",
                "소재지지번주소": "경기도 시흥시 정왕동 2560",
                "위도": 37.36,
                "경도": 126.71,
                "제공기관명": "경기도 시흥시",
            },
        ]
    )
    monkeypatch.setattr(source, "_read_csv", lambda _: raw.copy())

    df, *metadata = source._load_protection_zone()

    assert df["대상시설명"].tolist() == ["서울시설"]
    assert metadata == [
        "위도",
        "경도",
        "대상시설명",
        "소재지도로명주소",
        None,
        None,
        None,
    ]


def test_child_layer_aggregates_protection_zones_at_the_same_location():
    collector = ChildCollector()
    collector.csv = MagicMock()
    collector.public = MagicMock()
    collector.csv.get.return_value = pd.DataFrame(
        [
            {"csv_raw_id": 1, "geom": SimpleNamespace(x=127.0, y=37.5)},
            {"csv_raw_id": 2, "geom": SimpleNamespace(x=127.0, y=37.5)},
            {"csv_raw_id": 3, "geom": SimpleNamespace(x=127.1, y=37.6)},
        ]
    )
    collector.public.get.return_value = pd.DataFrame()

    records = collector.build_records()

    assert len(records) == 2
    assert {record["csv_raw_id"] for record in records} == {1, 3}


def test_cctv_source_corrects_known_coordinate_outliers(monkeypatch):
    source = CSVSource()
    raw = pd.DataFrame(
        [
            {
                "번호": 5953,
                "관리기관명": "서울특별시 성북구청",
                "소재지도로명주소": "서울특별시 성북구 성북동 15-137",
                "소재지지번주소": "서울특별시 성북구 선잠로5가길 40",
                "WGS84위도": 37.5986,
                "WGS84경도": 216.9947,
            },
            {
                "번호": 19223,
                "관리기관명": "서울특별시 도봉구청",
                "소재지도로명주소": "서울특별시 도봉구청 방학로10길70",
                "소재지지번주소": None,
                "WGS84위도": 37.03501,
                "WGS84경도": 127.035,
            },
        ]
    )
    monkeypatch.setattr(source, "_read_excel", lambda *_args, **_kwargs: raw.copy())

    df, *metadata = source._load_cctv()

    assert df["WGS84위도"].tolist() == [37.5986363173449, 37.6648983029005]
    assert df["WGS84경도"].tolist() == [126.994889082557, 127.034998844885]
    assert metadata == [
        "WGS84위도",
        "WGS84경도",
        None,
        "소재지지번주소",
        None,
        None,
        None,
    ]


def test_cctv_layer_aggregates_records_at_the_same_location():
    collector = SafetyCollector()
    collector.csv = MagicMock()
    collector.csv.get.return_value = pd.DataFrame(
        [
            {"csv_raw_id": 1, "geom": SimpleNamespace(x=127.0, y=37.5)},
            {"csv_raw_id": 2, "geom": SimpleNamespace(x=127.0, y=37.5)},
            {"csv_raw_id": 3, "geom": SimpleNamespace(x=127.1, y=37.6)},
        ]
    )

    records = collector.build_cctv_records()

    assert len(records) == 2
    assert {record["csv_raw_id"] for record in records} == {1, 3}


def test_street_tree_source_keeps_only_usable_seoul_lines(monkeypatch):
    source = CSVSource()
    raw = pd.DataFrame(
        [
            {
                "가로수길명": "정상 서울길",
                "가로수길시작위도": 37.50,
                "가로수길시작경도": 127.00,
                "가로수길종료위도": 37.51,
                "가로수길종료경도": 127.01,
                "제공기관명": "서울특별시 영등포구",
            },
            {
                "가로수길명": "좌표 오류",
                "가로수길시작위도": 37.33,
                "가로수길시작경도": 127.08,
                "가로수길종료위도": 37.34,
                "가로수길종료경도": 127.09,
                "제공기관명": "서울특별시 강동구",
            },
            {
                "가로수길명": "길이 없음",
                "가로수길시작위도": 37.52,
                "가로수길시작경도": 126.90,
                "가로수길종료위도": 37.52,
                "가로수길종료경도": 126.90,
                "제공기관명": "서울특별시 영등포구",
            },
            {
                "가로수길명": "경기도 길",
                "가로수길시작위도": 37.50,
                "가로수길시작경도": 126.80,
                "가로수길종료위도": 37.51,
                "가로수길종료경도": 126.81,
                "제공기관명": "경기도 부천시",
            },
        ]
    )
    monkeypatch.setattr(source, "_read_csv", lambda _: raw.copy())

    df, *metadata = source._load_street_tree()

    assert df["가로수길명"].tolist() == ["정상 서울길"]
    assert metadata == [
        "가로수길시작위도",
        "가로수길시작경도",
        "가로수길명",
        None,
        None,
        "가로수길종료위도",
        "가로수길종료경도",
    ]
