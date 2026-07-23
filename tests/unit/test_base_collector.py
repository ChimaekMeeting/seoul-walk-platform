import pandas as pd
import pytest

from src.data.collectors.base_collector import BaseNetworkCollector


def _network_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "노드링크 유형": "NODE",
                "노드 WKT": "POINT(126.0 37.0)",
                "노드 ID": 1,
                "노드 유형 코드": 2,
                "링크 WKT": None,
                "링크 ID": 0,
                "링크 유형 코드": None,
                "시작노드 ID": None,
                "종료노드 ID": None,
                "링크 길이": None,
                "고가도로": None,
                "지하철네트워크": None,
                "교량": None,
                "터널": None,
                "육교": 1,
                "횡단보도": 0,
                "공원,녹지": None,
                "건물내": None,
            },
            {
                "노드링크 유형": "LINK",
                "노드 WKT": None,
                "노드 ID": 0,
                "노드 유형 코드": None,
                "링크 WKT": "LINESTRING(126.0 37.0,126.1 37.1)",
                "링크 ID": 10,
                "링크 유형 코드": 1011,
                "시작노드 ID": 1,
                "종료노드 ID": 2,
                "링크 길이": 15.5,
                "고가도로": 0,
                "지하철네트워크": 0,
                "교량": 1,
                "터널": 0,
                "육교": 0,
                "횡단보도": 1,
                "공원,녹지": 0,
                "건물내": 0,
            },
            {
                "노드링크 유형": "LINK",
                "노드 WKT": None,
                "노드 ID": 0,
                "노드 유형 코드": None,
                "링크 WKT": "LINESTRING(126.1 37.1,126.2 37.2)",
                "링크 ID": 11,
                "링크 유형 코드": 100,
                "시작노드 ID": 2,
                "종료노드 ID": 3,
                "링크 길이": 20.0,
                "고가도로": 0,
                "지하철네트워크": 0,
                "교량": 0,
                "터널": 0,
                "육교": 0,
                "횡단보도": 0,
                "공원,녹지": 0,
                "건물내": 0,
            },
        ]
    )


def test_build_node_records_uses_node_rows_and_derives_missing_endpoints():
    collector = BaseNetworkCollector(_network_dataframe())

    records = {record["node_id"]: record for record in collector.build_node_records()}

    assert set(records) == {1, 2, 3}
    assert records[1]["node_type"] == "bus_stop"
    assert records[1]["raw_node_type_code"] == 2
    assert records[1]["raw_is_overpass"] is True
    assert records[1]["raw_is_crosswalk"] is False
    assert records[1]["geom"].data == "POINT(126.0 37.0)"

    assert records[2]["node_type"] == "derived_endpoint"
    assert records[2]["raw_node_type_code"] is None
    assert records[2]["raw_is_overpass"] is None
    assert records[2]["raw_is_crosswalk"] is None
    assert records[2]["geom"].data == "POINT(126.1 37.1)"


def test_build_edge_records_parses_access_code_and_flags():
    collector = BaseNetworkCollector(_network_dataframe())

    records = {record["link_id"]: record for record in collector.build_edge_records()}

    walkable = records[10]
    assert walkable["raw_link_type_code"] == "1011"
    assert walkable["allows_pedestrian"] is True
    assert walkable["allows_vehicle"] is False
    assert walkable["allows_bicycle"] is True
    assert walkable["allows_pm"] is True
    assert walkable["is_walkable"] is True
    assert walkable["raw_is_bridge"] is True
    assert walkable["raw_is_crosswalk"] is True

    vehicle_only = records[11]
    assert vehicle_only["raw_link_type_code"] == "0100"
    assert vehicle_only["allows_pedestrian"] is False
    assert vehicle_only["allows_vehicle"] is True
    assert vehicle_only["allows_bicycle"] is False
    assert vehicle_only["allows_pm"] is False
    assert vehicle_only["is_walkable"] is False


@pytest.mark.parametrize("value", [None, float("nan"), 2111, "road"])
def test_parse_link_type_code_rejects_missing_or_unknown_values(value):
    with pytest.raises((TypeError, ValueError)):
        BaseNetworkCollector.parse_link_type_code(value)


@pytest.mark.parametrize("value", [None, float("nan"), -1, 2, "yes"])
def test_parse_flag_rejects_missing_or_unknown_values(value):
    with pytest.raises((TypeError, ValueError)):
        BaseNetworkCollector.parse_flag(value)
