import logging
import re
from typing import Literal

import pandas as pd
from geoalchemy2.elements import WKTElement

from src.data.sources.csv_source import CSVSource
from src.repository.network.network_write_repository import NetworkWriteRepository

logger = logging.getLogger(__name__)


class BaseNetworkCollector:
    """
    서울시 도보 네트워크 CSV를 파싱하여 walk_nodes와 walk_edges에 저장합니다.
    """
    NODE_TYPE_MAP = {
        0: "general",
        1: "subway_entrance",
        2: "bus_stop",
        3: "visually_impaired_entrance",
    }

    def __init__(self, dataframe: pd.DataFrame | None = None):
        self.csv = CSVSource()
        df = dataframe if dataframe is not None else self.csv.load_walk_network()
        self.nodes_df = df[df["노드링크 유형"] == "NODE"].copy()
        self.edges_df = df[df["노드링크 유형"] == "LINK"].copy()

    @staticmethod
    def parse_flag(value) -> bool:
        if pd.isna(value):
            raise ValueError("NODE/LINK 플래그 값이 비어 있습니다.")
        normalized = int(float(value))
        if normalized not in (0, 1):
            raise ValueError(f"지원하지 않는 NODE/LINK 플래그 값: {value!r}")
        return normalized == 1

    @staticmethod
    def parse_link_type_code(value) -> str:
        if pd.isna(value):
            raise ValueError("LINK 행의 링크 유형 코드가 비어 있습니다.")
        code = str(int(float(value))).zfill(4)
        if len(code) != 4 or set(code) - {"0", "1"}:
            raise ValueError(f"지원하지 않는 링크 유형 코드: {value!r}")
        return code

    def extract_endpoints(self, wkt: str):
        coords = re.findall(r"([\d.]+)\s+([\d.]+)", wkt)
        if not coords:
            return None, None
        return (float(coords[0][0]), float(coords[0][1])), (float(coords[-1][0]), float(coords[-1][1]))

    def build_node_records(self) -> list:
        records_by_id = {}

        node_columns = ["노드 ID", "노드 유형 코드", "육교", "횡단보도", "노드 WKT"]
        for node_id, type_code, overpass, crosswalk, node_wkt in self.nodes_df[node_columns].itertuples(
            index=False,
            name=None,
        ):
            raw_type_code = None if pd.isna(type_code) else int(float(type_code))
            raw_is_overpass = self.parse_flag(overpass)
            records_by_id[int(node_id)] = {
                "node_id": int(node_id),
                "node_type": self.NODE_TYPE_MAP.get(raw_type_code, "unknown"),
                "raw_node_type_code": raw_type_code,
                "raw_is_crosswalk": self.parse_flag(crosswalk),
                "raw_is_overpass": raw_is_overpass,
                "is_underground": False,
                "is_overpass": raw_is_overpass,
                "geom": WKTElement(node_wkt, srid=4326),
            }

        derived_count = 0
        edge_columns = ["시작노드 ID", "종료노드 ID", "링크 WKT"]
        for start_node, end_node, link_wkt in self.edges_df[edge_columns].itertuples(
            index=False,
            name=None,
        ):
            start_pt, end_pt = self.extract_endpoints(link_wkt)
            for node_id, point in ((int(start_node), start_pt), (int(end_node), end_pt)):
                if node_id in records_by_id or point is None:
                    continue
                lon, lat = point
                records_by_id[node_id] = {
                    "node_id": node_id,
                    "node_type": "derived_endpoint",
                    "raw_node_type_code": None,
                    "raw_is_crosswalk": None,
                    "raw_is_overpass": None,
                    "is_underground": False,
                    "is_overpass": False,
                    "geom": WKTElement(f"POINT({lon} {lat})", srid=4326),
                }
                derived_count += 1

        logger.info(
            "NODE 원본 %d개, LINK endpoint 보완 %d개",
            len(self.nodes_df),
            derived_count,
        )
        return list(records_by_id.values())

    def build_edge_records(self) -> list:
        columns = [
            "링크 ID",
            "시작노드 ID",
            "종료노드 ID",
            "링크 길이",
            "링크 유형 코드",
            "고가도로",
            "지하철네트워크",
            "교량",
            "터널",
            "육교",
            "횡단보도",
            "공원,녹지",
            "건물내",
            "링크 WKT",
        ]
        records = []
        for row in self.edges_df[columns].itertuples(index=False, name=None):
            (
                link_id,
                start_node,
                end_node,
                length_m,
                link_type_code,
                elevated,
                subway_network,
                bridge,
                tunnel,
                overpass,
                crosswalk,
                park_green,
                building_inside,
                link_wkt,
            ) = row
            code = self.parse_link_type_code(link_type_code)
            allows_pedestrian, allows_vehicle, allows_bicycle, allows_pm = (
                digit == "1" for digit in code
            )
            records.append(
                {
                    "link_id": int(link_id),
                    "start_node": int(start_node),
                    "end_node": int(end_node),
                    "raw_link_type_code": code,
                    "allows_pedestrian": allows_pedestrian,
                    "allows_vehicle": allows_vehicle,
                    "allows_bicycle": allows_bicycle,
                    "allows_pm": allows_pm,
                    "is_walkable": allows_pedestrian,
                    "raw_is_elevated": self.parse_flag(elevated),
                    "raw_is_subway_network": self.parse_flag(subway_network),
                    "raw_is_bridge": self.parse_flag(bridge),
                    "raw_is_tunnel": self.parse_flag(tunnel),
                    "raw_is_overpass": self.parse_flag(overpass),
                    "raw_is_crosswalk": self.parse_flag(crosswalk),
                    "raw_is_park_green": self.parse_flag(park_green),
                    "raw_is_building_inside": self.parse_flag(building_inside),
                    "length_m": float(length_m),
                    "geom": WKTElement(link_wkt, srid=4326),
                }
            )
        return records

    def build_records(self) -> tuple[list[dict], list[dict]]:
        nodes = self.build_node_records()
        edges = self.build_edge_records()
        logger.info("도보 네트워크 빌드 완료: nodes=%d, edges=%d", len(nodes), len(edges))
        return nodes, edges

    def upsert(self) -> None:
        nodes, edges = self.build_records()
        NetworkWriteRepository.upsert(nodes, edges)

    def rebuild(self) -> None:
        nodes, edges = self.build_records()
        NetworkWriteRepository.rebuild(nodes, edges)

    def save(self, mode: Literal["upsert", "rebuild"] = "upsert") -> None:
        """
        하위 호환용 진입점입니다. 신규 호출부에서는 upsert/rebuild를 직접 호출합니다.
        """
        if mode == "upsert":
            self.upsert()
            return
        if mode == "rebuild":
            self.rebuild()
            return
        raise ValueError(f"지원하지 않는 네트워크 적재 모드: {mode}")


if __name__ == "__main__":
    collector = BaseNetworkCollector()
    collector.upsert()
