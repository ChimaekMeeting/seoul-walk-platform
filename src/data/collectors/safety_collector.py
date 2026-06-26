import logging

import pandas as pd

from src.data.sources.csv_source import CSVSource
from src.data.utils import CollectorUtils
from src.repository.network.edge_repository import EdgeRepository
from src.repository.layer.safety_repository import SafetyRepository

logger = logging.getLogger(__name__)


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
                "geom":        CollectorUtils.make_point(row["geom"].y, row["geom"].x),
            })
        logger.debug("streetlight %d개 빌드", len(records))
        return records

    def build_cctv_records(self) -> list:
        gdf = self.csv.get("type", "cctv")
        records = []
        for _, row in gdf.iterrows():
            records.append({
                "csv_raw_id":  row.get("csv_raw_id"),
                "safety_type": "cctv",
                "geom":        CollectorUtils.make_point(row["geom"].y, row["geom"].x),
            })
        logger.debug("cctv %d개 빌드", len(records))
        return records

    def update_node(self) -> None:
        streetlight = self.build_streetlight_records()
        cctv = self.build_cctv_records()
        records = streetlight + cctv
        logger.info("safety_layer %d개 저장 시작 (streetlight=%d, cctv=%d)",
                    len(records), len(streetlight), len(cctv))
        SafetyRepository.save_all(records)

    def update_edge(self) -> None:
        EdgeRepository.ensure_score_column("safety_score")
        CollectorUtils.update_edge_scores("safety_score", SafetyRepository.get_safety_h3_counts())

    def save(self) -> None:
        self.update_node()
        self.update_edge()


if __name__ == "__main__":
    collector = SafetyCollector()
    collector.save()
