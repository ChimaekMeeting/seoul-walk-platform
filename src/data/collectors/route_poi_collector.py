import logging
import re

from src.data.sources.csv_source import CSVSource
from src.data.utils.collector_utils import CollectorUtils
from src.data.utils.serialization import to_json_value
from src.repository.layer.route_poi_repository import RoutePoiRepository

logger = logging.getLogger(__name__)


class RoutePoiCollector:
    """승인된 Point 원본을 경로 주변 POI로 저장하고 도보망에 연결합니다."""

    SOURCES = (
        {
            "value": "running_park",
            "source_name": "major_park",
            "category": "park",
            "id_field": None,
        },
        {
            "value": "toilet",
            "source_name": "public_toilet",
            "category": "toilet",
            "id_field": "연번",
        },
        {
            "value": "bus_stop",
            "source_name": "bus_stop",
            "category": "transit",
            "id_field": "정류소번호",
        },
        {
            "value": "subway_lift",
            "source_name": "subway_lift",
            "category": "accessibility",
            "id_field": "노드 ID",
        },
        {
            "value": "subway_elevator",
            "source_name": "subway_elevator",
            "category": "accessibility",
            "id_field": "노드 ID",
        },
    )

    def __init__(self, csv_source: CSVSource | None = None):
        self.csv = csv_source or CSVSource()
        self._toilet_detail_indexes = None

    @staticmethod
    def _normalize_match_value(value) -> str:
        if value is None:
            return ""
        return re.sub(r"[^0-9a-z가-힣]", "", str(value).lower())

    def _load_toilet_detail_indexes(self) -> dict[str, dict]:
        if self._toilet_detail_indexes is not None:
            return self._toilet_detail_indexes

        details = self.csv.load_toilet_details()
        indexes = {}
        for index_name, column in (
            ("name", "화장실명"),
            ("road_address", "소재지도로명주소"),
            ("lot_address", "소재지지번주소"),
        ):
            grouped = {}
            for _, detail in details.iterrows():
                key = self._normalize_match_value(detail.get(column))
                if key:
                    grouped.setdefault(key, []).append(detail)
            indexes[index_name] = {
                key: rows[0]
                for key, rows in grouped.items()
                if len(rows) == 1
            }
        self._toilet_detail_indexes = indexes
        return indexes

    def _find_toilet_detail(self, row):
        indexes = self._load_toilet_detail_indexes()
        candidates = (
            ("road_address", row.get("address")),
            ("lot_address", row.get("지번주소")),
            ("name", row.get("name")),
        )
        for index_name, value in candidates:
            key = self._normalize_match_value(value)
            if key and key in indexes[index_name]:
                return indexes[index_name][key]
        return None

    def _toilet_detail_properties(self, row) -> dict:
        detail = self._find_toilet_detail(row)
        if detail is None:
            return {"상세정보_결합상태": "미결합"}

        excluded = {
            "화장실명",
            "소재지도로명주소",
            "소재지지번주소",
        }
        properties = {
            column: to_json_value(detail[column])
            for column in detail.index
            if column not in excluded
        }
        properties["상세정보_결합상태"] = "결합"
        return properties

    @staticmethod
    def _source_id(row, id_field: str | None) -> str:
        value = row.get(id_field) if id_field else None
        if value is None or str(value).strip() in {"", "nan", "None"}:
            value = row["csv_raw_id"]
        return str(value)

    def build_records(self, source: dict) -> list[dict]:
        gdf = self.csv.get("type", source["value"])
        records = []
        seen_source_ids = set()
        for _, row in gdf.iterrows():
            geometry = row["geom"]
            if geometry is None or geometry.geom_type != "Point":
                continue
            source_id = self._source_id(row, source["id_field"])
            if source_id in seen_source_ids:
                continue
            seen_source_ids.add(source_id)

            excluded = {
                "geom",
                "csv_raw_id",
                "name",
                "address",
            }
            properties = {
                column: to_json_value(row[column])
                for column in row.index
                if column not in excluded
            }
            if source["value"] == "toilet":
                properties.update(self._toilet_detail_properties(row))
            records.append(
                {
                    "source_name": source["source_name"],
                    "source_id": source_id,
                    "category": source["category"],
                    "name": to_json_value(row.get("name")),
                    "address": to_json_value(row.get("address")),
                    "properties": properties or None,
                    "geom": CollectorUtils.make_point(geometry.y, geometry.x),
                }
            )
        return records

    def save(self) -> None:
        for source in self.SOURCES:
            records = self.build_records(source)
            RoutePoiRepository.replace_source(source["source_name"], records)
            connected = RoutePoiRepository.connect_source_to_network(
                source["source_name"],
                max_distance_m=50.0,
            )
            logger.info(
                "%s POI 저장 %d개, 도보망 50m 연결 %d개",
                source["source_name"],
                len(records),
                connected,
            )
