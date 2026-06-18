import pandas as pd

from src.data.sources.csv_source import CSVSource
from src.data.utils import CollectorUtils
from src.repository.network.edge_repository import EdgeRepository
from src.repository.layer.safety_repository import SafetyRepository


class SafetyCollector:
    def __init__(self):
        self.csv = CSVSource()

    def build_streetlight_records(self) -> list:
        gdf = self.csv.get("type", "streetlight")
        records = []
        for _, row in gdf.iterrows():
            records.append({
                "csv_raw_id":  row.get("csv_raw_id"),
                "safety_type": "streetlight",
                "address":     str(row.get("소재지도로명주소", "")) if pd.notna(row.get("소재지도로명주소")) else "",
                "geom":        CollectorUtils.make_point(row.geometry.y, row.geometry.x),
            })
        return records

    def build_cctv_records(self) -> list:
        gdf = self.csv.get("type", "cctv")
        records = []
        for _, row in gdf.iterrows():
            records.append({
                "csv_raw_id":  row.get("csv_raw_id"),
                "safety_type": "cctv",
                "address":     str(row.get("소재지도로명주소", "")) if pd.notna(row.get("소재지도로명주소")) else "",
                "geom":        CollectorUtils.make_point(row.geometry.y, row.geometry.x),
            })
        return records

    def update_node(self) -> None:
        SafetyRepository.save_all(self.build_streetlight_records() + self.build_cctv_records())

    def update_edge(self) -> None:
        EdgeRepository.ensure_score_column("safety_score")
        CollectorUtils.update_edge_scores("safety_score", SafetyRepository.get_safety_h3_counts())

    def save(self) -> None:
        if SafetyRepository.is_populated():
            print("  ⏭️  safety_layer 이미 적재됨, 스킵")
            return
        self.update_node()
        self.update_edge()


if __name__ == "__main__":
    collector = SafetyCollector()
    collector.save()
