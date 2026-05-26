import re
import pandas as pd
from geoalchemy2.elements import WKTElement
from src.repository.route.node_repository import NodeRepository
from src.repository.route.edge_repository import EdgeRepository


class BaseNetworkCollector:
    def __init__(self, csv_path: str = "src/data/raw/서울시 자치구별 도보 네트워크 공간정보.csv"):
        self.csv_path = csv_path
        self.data = self.load_data()

    def load_data(self) -> pd.DataFrame:
        """
        데이터를 로드합니다.
        """
        try:
            return pd.read_csv(self.csv_path, encoding='cp949')
        except UnicodeDecodeError:
            return pd.read_csv(self.csv_path, encoding='utf-8')

    def extract_endpoints(self, wkt: str):
        """
        start 좌표와 end 좌표를 분리합니다.
        """
        coords = re.findall(r"([\d.]+)\s+([\d.]+)", wkt)
        if not coords:
            return None, None
        return (float(coords[0][0]), float(coords[0][1])), (float(coords[-1][0]), float(coords[-1][1]))

    def build_edge_records(self, edges_df: pd.DataFrame) -> list:
        """
        walk_edges INSERT용 dict 리스트를 변환합니다.
        """
        return [
            {
                "link_id":    int(row['링크 ID']),
                "start_node": int(row['시작노드 ID']),
                "end_node":   int(row['종료노드 ID']),
                "length_m":   float(row['링크 길이']),
                "road_type":  str(row['링크 유형 코드']) if pd.notna(row['링크 유형 코드']) else None,
                "path_type":  "sidewalk",
                "geom":       WKTElement(row['링크 WKT'], srid=4326),
            }
            for _, row in edges_df.iterrows()
        ]

    def build_node_records(self, edges_df: pd.DataFrame) -> list:
        """
        walk_nodes INSERT용 dict 리스트를 반환합니다.
        """
        print("노드 좌표 추출 중...")
        node_map = {}
        for _, row in edges_df.iterrows():
            start_pt, end_pt = self.extract_endpoints(row['링크 WKT'])
            if start_pt:
                node_map[int(row['시작노드 ID'])] = start_pt
            if end_pt:
                node_map[int(row['종료노드 ID'])] = end_pt

        print(f"추출된 노드 수: {len(node_map)}")
        return [
            {
                "node_id":        nid,
                "is_underground": False,
                "is_overpass":    False,
                "geom":           WKTElement(f"POINT({lng} {lat})", srid=4326),
            }
            for nid, (lng, lat) in node_map.items()
        ]

    def save(self):
        """
        데이터를 저장합니다.
        """
        print(f"[{self.csv_path}] 고속 벌크 적재를 시작합니다...")

        edges_df = self.data[self.data['노드링크 유형'] == 'LINK'].copy()

        edge_records = self.build_edge_records(edges_df)
        node_records = self.build_node_records(edges_df)

        EdgeRepository.truncate()
        NodeRepository.truncate()

        NodeRepository.save_all(node_records)
        EdgeRepository.save_all(edge_records)


if __name__ == "__main__":
    collector = BaseNetworkCollector()
    collector.save()