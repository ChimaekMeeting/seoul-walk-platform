import re
import pandas as pd
from geoalchemy2.elements import WKTElement
from src.repository.network.node_repository import NodeRepository
from src.repository.network.edge_repository import EdgeRepository


class BaseNetworkCollector:
    """
    서울시 도보 네트워크 CSV를 파싱하여 walk_nodes와 walk_edges에 저장합니다.
    """
    def __init__(self):
        self.CSV_PATH = "src/data/raw/서울시 자치구별 도보 네트워크 공간정보.csv"
        df = self.load_data()
        self.edges_df = df[df["노드링크 유형"] == "LINK"].copy()

    def load_data(self) -> pd.DataFrame:
        """
        CSV 파일을 인코딩 자동 감지로 로드합니다.
        """
        try:
            return pd.read_csv(self.CSV_PATH, encoding="cp949")
        except UnicodeDecodeError:
            return pd.read_csv(self.CSV_PATH, encoding="utf-8")

    def extract_endpoints(self, wkt: str):
        """
        WKT LINESTRING에서 시작 좌표와 종료 좌표를 추출합니다.
        """
        coords = re.findall(r"([\d.]+)\s+([\d.]+)", wkt)
        if not coords:
            return None, None
        return (float(coords[0][0]), float(coords[0][1])), (float(coords[-1][0]), float(coords[-1][1]))

    def build_node_records(self) -> list:
        """
        LINK 행의 시작·종료 좌표를 수집하여 walk_nodes INSERT용 dict 리스트를 반환합니다.
        """
        node_map = {}
        for _, row in self.edges_df.iterrows():
            start_pt, end_pt = self.extract_endpoints(row["링크 WKT"])
            if start_pt:
                node_map[int(row["시작노드 ID"])] = start_pt
            if end_pt:
                node_map[int(row["종료노드 ID"])] = end_pt

        return [
            {
                "node_id":        nid,
                "is_underground": False,
                "is_overpass":    False,
                "geom":           WKTElement(f"POINT({lon} {lat})", srid=4326),
            }
            for nid, (lon, lat) in node_map.items()
        ]

    def build_edge_records(self) -> list:
        """
        LINK 행을 walk_edges INSERT용 dict 리스트로 변환합니다.
        """
        return [
            {
                "link_id":    int(row["링크 ID"]),
                "start_node": int(row["시작노드 ID"]),
                "end_node":   int(row["종료노드 ID"]),
                "length_m":   float(row["링크 길이"]),
                "geom":       WKTElement(row["링크 WKT"], srid=4326),
            }
            for _, row in self.edges_df.iterrows()
        ]

    def update_node(self) -> None:
        """
        walk_edges와 walk_nodes를 초기화하고 CSV에서 추출한 노드를 저장합니다.
        """
        EdgeRepository.truncate()
        NodeRepository.truncate()
        NodeRepository.save_all(self.build_node_records())

    def update_edge(self) -> None:
        """
        CSV에서 추출한 엣지를 walk_edges에 저장합니다.
        """
        EdgeRepository.save_all(self.build_edge_records())

    def save(self) -> None:
        """
        walk_nodes를 초기화·저장한 뒤 walk_edges를 저장합니다.
        """
        self.update_node()
        self.update_edge()


if __name__ == "__main__":
    collector = BaseNetworkCollector()
    collector.save()
