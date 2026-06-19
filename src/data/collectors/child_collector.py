from dotenv import load_dotenv

from src.data.sources.csv_source import CSVSource
from src.data.sources.public_source import PublicSource
from src.data.utils.collector_utils import CollectorUtils
from src.repository.layer.child_repository import ChildRepository
from src.repository.network.edge_repository import EdgeRepository

load_dotenv()


class ChildCollector:
    def __init__(self):
        self.csv = CSVSource()
        self.public = PublicSource()

    def build_records(self) -> list[dict]:
        records = []

        # 어린이보호구역 (csv_raw → child_layer)
        gdf = self.csv.get("type", "protection_zone")
        for _, row in gdf.iterrows():
            records.append({
                "csv_raw_id":    row.get("csv_raw_id"),
                "public_raw_id": None,
                "category":      "어린이보호구역",
                "geom":          CollectorUtils.make_point(row["geom"].y, row["geom"].x),
            })

        # 어린이놀이시설 (public_raw → child_layer)
        gdf = self.public.get("type", "play_facility")
        for _, row in gdf.iterrows():
            records.append({
                "csv_raw_id":    None,
                "public_raw_id": row.get("public_raw_id"),
                "category":      "어린이놀이시설",
                "geom":          CollectorUtils.make_point(row["geom"].y, row["geom"].x),
            })

        return records

    def update_node(self) -> None:
        records = self.build_records()
        ChildRepository.save_all(records)

    def update_edge(self) -> None:
        EdgeRepository.ensure_score_column("child_score")
        CollectorUtils.update_edge_scores("child_score", ChildRepository.get_child_h3_counts())

    def save(self) -> None:
        if ChildRepository.is_populated():
            print("  ⏭️  child_layer 이미 적재됨, 스킵")
            return
        self.update_node()
        self.update_edge()


if __name__ == "__main__":
    collector = ChildCollector()
    collector.save()
