import logging

from src.data.sources.csv_source import CSVSource
from src.data.utils import CollectorUtils
from src.repository.network.edge_repository import EdgeRepository
from src.repository.layer.safety_repository import SafetyRepository
from src.data.sources.public_source import PublicSource

logger = logging.getLogger(__name__)

class SafetyCollector:
    def __init__(self):
        self.csv = CSVSource()
        self.public = PublicSource()

    def build_streetlight_records(self) -> list:
        gdf = self.csv.get("type", "streetlight")
        if gdf.empty:
            return []

        location_keys = gdf["geom"].map(lambda geom: (geom.y, geom.x))
        location_gdf = gdf.loc[~location_keys.duplicated()]
        records = []
        for _, row in location_gdf.iterrows():
            records.append({
                "csv_raw_id":  row.get("csv_raw_id"),
                "safety_type": "streetlight",
                "geom":        CollectorUtils.make_point(row["geom"].y, row["geom"].x),
            })
        logger.debug(
            "streetlight 원본 %d개를 위치 %d개로 집계",
            len(gdf),
            len(records),
        )
        return records

    def build_cctv_records(self) -> list:
        gdf = self.csv.get("type", "cctv")
        if gdf.empty:
            return []

        location_keys = gdf["geom"].map(lambda geom: (geom.y, geom.x))
        location_gdf = gdf.loc[~location_keys.duplicated()]
        records = []
        for _, row in location_gdf.iterrows():
            records.append({
                "csv_raw_id":  row.get("csv_raw_id"),
                "safety_type": "cctv",
                "geom":        CollectorUtils.make_point(row["geom"].y, row["geom"].x),
            })
        logger.debug(
            "cctv 원본 %d개를 위치 %d개로 집계",
            len(gdf),
            len(records),
        )
        return records
    
    def build_accident_records(self) -> list:
        gdf = self.public.get("type", "accident_zone")
        records = []
        for _, row in gdf.iterrows():
            records.append({
                "csv_raw_id":    None,
                "public_raw_id": row.get("public_raw_id"),
                "safety_type":   "accident_zone",
                "geom":          CollectorUtils.make_point(row["geom"].y, row["geom"].x),
            })
        return records

    def update_accident(self) -> None:
        records = self.build_accident_records()
        if not records:
            logger.warning("수집된 accident_zone 데이터가 없습니다.")
            return
        SafetyRepository.replace_types(
            records,
            safety_types={"streetlight", "cctv"},
        )
        self.update_edge()
        logger.info("accident_zone 적재 완료: %d건", len(records))

    def update_node(self) -> None:
        streetlight = self.build_streetlight_records()
        cctv = self.build_cctv_records()
        records = streetlight + cctv
        logger.info("safety_layer %d개 저장 시작 (streetlight=%d, cctv=%d)",
                    len(records), len(streetlight), len(cctv))
        SafetyRepository.save_all(records)

    def update_edge(self) -> None:
        EdgeRepository.ensure_score_column("safety_score")
        CollectorUtils.update_edge_scores("safety_score", SafetyRepository.get_safety_counts_by_edge())

    def save(self) -> None:
        self.update_node()
        self.update_edge()


if __name__ == "__main__":
    collector = SafetyCollector()
    collector.save()
