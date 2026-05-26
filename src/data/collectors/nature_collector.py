import pandas as pd

from src.data.utils import CollectorUtils
from src.repository.route.edge_repository import EdgeRepository
from src.repository.route.poi_repository import NatureRepository


class NatureCollector:
    def __init__(self):
        self.data = self.load_data()

    def load_data(self) -> dict:
        """
        데이터(공원, 가로수길)를 로드합니다.
        """
        return {
            "park":      pd.read_csv("src/data/raw/서울시 주요 공원현황.csv", encoding="cp949"),
            "tree_road": pd.read_csv("src/data/raw/전국가로수길정보표준데이터.csv", encoding="cp949"),
        }

    def build_park_records(self) -> list:
        """
        서울시 주요 공원 데이터를 파싱하여 INSERT용 dict 리스트로 반환합니다.
        """
        df = self.data["park"]
        records = []
        for _, row in df.iterrows():
            if pd.isna(row["X좌표(WGS84)"]) or pd.isna(row["Y좌표(WGS84)"]):
                continue
            records.append({
                "poi_type": "park",
                "name": str(row["공원명"]) if pd.notna(row.get("공원명")) else "",
                "geom": CollectorUtils.make_point(row["Y좌표(WGS84)"], row["X좌표(WGS84)"]),
            })
        return records

    def build_tree_road_records(self) -> list:
        """
        서울 가로수길 데이터를 파싱하여 INSERT용 dict 리스트로 반환합니다.
        """
        df = self.data["tree_road"]
        seoul = df[df["제공기관명"].str.contains("서울", na=False)]
        records = []
        for _, row in seoul.iterrows():
            if pd.isna(row["가로수길시작경도"]) or pd.isna(row["가로수길시작위도"]):
                continue
            records.append({
                "poi_type": "tree_road",
                "name": str(row["가로수길명"]) if pd.notna(row.get("가로수길명")) else "",
                "geom": CollectorUtils.make_point(row["가로수길시작위도"], row["가로수길시작경도"]),
            })
        return records

    def update_edge(self) -> None:
        """
        자연/녹지 밀도 기반으로 walk_edges.nature_score를 업데이트합니다.
        """
        EdgeRepository.ensure_score_column("nature_score")
        CollectorUtils.update_edge_scores("nature_score", NatureRepository.get_nature_h3_counts())

    def save(self) -> None:
        """
        poi_layer를 초기화하고 데이터를 수집·저장한 뒤 edge를 업데이트합니다.
        """
        NatureRepository.truncate()

        records = self.build_park_records() + self.build_tree_road_records()
        NatureRepository.save_all(records)

        self.update_edge()


if __name__ == "__main__":
    collector = NatureCollector()
    collector.save()
