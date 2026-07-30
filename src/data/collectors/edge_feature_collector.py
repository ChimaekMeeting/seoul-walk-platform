import logging

from geoalchemy2.elements import WKTElement

from src.data.sources.csv_source import CSVSource
from src.data.utils.serialization import to_json_value
from src.repository.layer.edge_feature_repository import EdgeFeatureRepository

logger = logging.getLogger(__name__)


class EdgeFeatureCollector:
    """
    외부 Line을 검증 후보 Layer로 보존합니다.

    WalkEdge에 도로명이 없으므로 단순 거리만으로 확정 Tag를 만들지 않습니다.
    """

    SOURCES = (
        {
            "value": "street_tree",
            "source_name": "street_tree",
            "feature_type": "street_tree_candidate",
        },
        {
            "value": "pedestrian_priority",
            "source_name": "pedestrian_priority",
            "feature_type": "pedestrian_priority_candidate",
        },
        {
            "value": "tunnel",
            "source_name": "external_tunnel",
            "feature_type": "tunnel_verification",
        },
    )

    def __init__(self, csv_source: CSVSource | None = None):
        self.csv = csv_source or CSVSource()

    def build_records(self, source: dict) -> list[dict]:
        gdf = self.csv.get("type", source["value"])
        records = []
        for _, row in gdf.iterrows():
            geometry = row["geom"]
            if geometry is None or geometry.geom_type != "LineString":
                continue
            source_id = str(row["csv_raw_id"])
            excluded = {"geom", "csv_raw_id", "name"}
            properties = {
                column: to_json_value(row[column])
                for column in row.index
                if column not in excluded
            }
            records.append(
                {
                    "source_name": source["source_name"],
                    "source_id": source_id,
                    "feature_type": source["feature_type"],
                    "name": to_json_value(row.get("name")),
                    "verification_status": "candidate",
                    "properties": properties or None,
                    "geom": WKTElement(geometry.wkt, srid=4326),
                }
            )
        return records

    def save(self) -> None:
        for source in self.SOURCES:
            records = self.build_records(source)
            EdgeFeatureRepository.replace_source(
                source["source_name"],
                records,
            )
            logger.info(
                "%s 검증 후보 Line %d개 저장",
                source["source_name"],
                len(records),
            )
