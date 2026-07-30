import logging

from dotenv import load_dotenv

from src.data.sources.csv_source import CSVSource
from src.data.sources.public_source import PublicSource
from src.data.utils.collector_utils import CollectorUtils
from src.repository.layer.child_repository import ChildRepository
from src.repository.network.edge_repository import EdgeRepository

load_dotenv()

logger = logging.getLogger(__name__)


class ChildCollector:
    def __init__(self):
        self.csv = CSVSource()
        self.public = PublicSource()

    def build_records(self, include_play_facility: bool = True) -> list[dict]:
        records = []

        # 어린이보호구역 (csv_raw → child_layer)
        gdf = self.csv.get("type", "protection_zone")
        if not gdf.empty:
            location_keys = gdf["geom"].map(lambda geom: (geom.y, geom.x))
            protection_gdf = gdf.loc[~location_keys.duplicated()]
        else:
            protection_gdf = gdf
        protection_count = 0
        for _, row in protection_gdf.iterrows():
            records.append({
                "csv_raw_id":    row.get("csv_raw_id"),
                "public_raw_id": None,
                "category":      "어린이보호구역",
                "geom":          CollectorUtils.make_point(row["geom"].y, row["geom"].x),
            })
            protection_count += 1

        # 어린이놀이시설 (public_raw → child_layer)
        play_count = 0
        if include_play_facility:
            play_gdf = self.public.get("type", "play_facility")
            for _, row in play_gdf.iterrows():
                records.append({
                    "csv_raw_id":    None,
                    "public_raw_id": row.get("public_raw_id"),
                    "category":      "어린이놀이시설",
                    "geom":          CollectorUtils.make_point(row["geom"].y, row["geom"].x),
                })
                play_count += 1

        logger.debug(
            "어린이보호구역 RAW %d개를 위치 %d개로 집계, 어린이놀이시설 %d개 빌드",
            len(protection_gdf),
            protection_count,
            play_count,
        )
        return records

    def update_node(self, include_play_facility: bool = True) -> None:
        records = self.build_records(include_play_facility=include_play_facility)
        logger.info("child_layer %d개 저장 시작", len(records))
        categories = {"어린이보호구역"}
        if include_play_facility:
            categories.add("어린이놀이시설")
        ChildRepository.replace_categories(records, categories=categories)

    def update_edge(self) -> None:
        EdgeRepository.ensure_score_column("child_score")
        CollectorUtils.update_edge_scores("child_score", ChildRepository.get_child_h3_counts())
        updated = ChildRepository.update_nearest_school_zone_edges(
            max_distance_m=50.0
        )
        logger.info("어린이보호구역 최근접 차량 주의 Edge %d개 표시", updated)

    def save(self, include_play_facility: bool = True) -> None:
        self.update_node(include_play_facility=include_play_facility)
        self.update_edge()


if __name__ == "__main__":
    collector = ChildCollector()
    collector.save()
