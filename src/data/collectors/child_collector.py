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
            name = row.get("name")
            if not name:
                continue
            records.append({
                "csv_raw_id":    row.get("csv_raw_id"),
                "public_raw_id": None,
                "name":          name,
                "category":      "어린이보호구역",
                "address":       row.get("소재지도로명주소"),
                "geom":          CollectorUtils.make_point(row.geometry.y, row.geometry.x),
            })

        # 어린이놀이시설 (public_raw → child_layer)
        gdf = self.public.get("type", "play_facility")
        for _, row in gdf.iterrows():
            records.append({
                "csv_raw_id":    None,
                "public_raw_id": row.get("public_raw_id"),
                "name":          row.get("pfctNm") or row.get("name"),
                "category":      "어린이놀이시설",
                "address":       row.get("ronaAddr"),
                "geom":          CollectorUtils.make_point(row.geometry.y, row.geometry.x),
            })

        return records

    def update_node(self) -> None:
        records = self.build_records()
        ChildRepository.save_all(records)
        print(f"  ✅ 총 {len(records)}개 저장 완료")

    def update_edge(self) -> None:
        EdgeRepository.ensure_score_column("child_score")
        CollectorUtils.update_edge_scores("child_score", ChildRepository.get_child_h3_counts())
        print("  ✅ child_score 업데이트 완료")

    def save(self) -> None:
        if ChildRepository.is_populated():
            print("  ⏭️  child_layer 이미 적재됨, 스킵")
            return
        self.update_node()
        self.update_edge()


if __name__ == "__main__":
    collector = ChildCollector()
    collector.save()
