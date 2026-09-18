import logging

from src.data.sources.csv_source import CSVSource
from src.data.utils import CollectorUtils
from src.repository.network.edge_repository import EdgeRepository
from src.repository.layer.safety_repository import SafetyRepository
from src.data.sources.public_source import PublicSource

logger = logging.getLogger(__name__)

class SafetyCollector:
    # 한 좌표에 설치목적이 여러 개 등록된 경우(원본 518좌표, 그중 차량·비차량 혼재 357좌표)
    # 보행자 관련성이 높은 목적을 대표값으로 채택한다.
    # 커버리지 계산은 좌표 단위이므로 좌표당 대표 목적 하나로 충분하다.
    CCTV_PURPOSE_PRIORITY: list[str] = [
        "생활방범", "어린이보호", "다목적", "시설물관리",
        "재난재해", "쓰레기단속", "기타",
        "교통단속", "차량방범", "교통정보수집",
    ]

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
                "purpose":     None,
                "geom":        CollectorUtils.make_point(row["geom"].y, row["geom"].x),
            })
        logger.debug(
            "streetlight 원본 %d개를 위치 %d개로 집계",
            len(gdf),
            len(records),
        )
        return records

    def _build_point_records(self, query_value: str, safety_type: str) -> list:
        """
        좌표만 있는 안전 시설물(가로등·보안등)을 좌표 단위 레코드로 만듭니다.
        커버리지 계산은 좌표 단위이므로 같은 좌표의 중복 행은 하나로 합칩니다.
        """
        gdf = self.csv.get("type", query_value)
        if gdf.empty:
            logger.warning("%s 원본이 비어 있습니다.", query_value)
            return []

        location_keys = gdf["geom"].map(lambda geom: (geom.y, geom.x))
        location_gdf = gdf.loc[~location_keys.duplicated()]
        records = [
            {
                "csv_raw_id":  row.get("csv_raw_id"),
                "safety_type": safety_type,
                "purpose":     None,
                "geom":        CollectorUtils.make_point(row["geom"].y, row["geom"].x),
            }
            for _, row in location_gdf.iterrows()
        ]
        logger.info(
            "%s 원본 %d행을 위치 %d개로 집계", query_value, len(gdf), len(records)
        )
        return records

    def build_streetlamp_records(self) -> list:
        """서울특별시 가로등."""
        return self._build_point_records("streetlamp", "streetlamp")

    def build_security_light_records(self) -> list:
        """서울시 보안등."""
        return self._build_point_records("security_light", "security_light")

    def build_cctv_records(self) -> list:
        gdf = self.csv.get("type", "cctv")
        if gdf.empty:
            return []

        if "설치목적구분" in gdf.columns:
            rank = {name: i for i, name in enumerate(self.CCTV_PURPOSE_PRIORITY)}
            gdf = gdf.assign(
                _purpose=gdf["설치목적구분"],
                _priority=gdf["설치목적구분"].map(lambda v: rank.get(v, len(rank))),
            ).sort_values("_priority", kind="stable")
        else:
            logger.warning("CCTV 원본에 설치목적구분 열이 없습니다. purpose를 비워 둡니다.")
            gdf = gdf.assign(_purpose=None)

        location_keys = gdf["geom"].map(lambda geom: (geom.y, geom.x))
        location_gdf = gdf.loc[~location_keys.duplicated()]
        records = []
        for _, row in location_gdf.iterrows():
            records.append({
                "csv_raw_id":  row.get("csv_raw_id"),
                "safety_type": "cctv",
                "purpose":     row.get("_purpose"),
                "geom":        CollectorUtils.make_point(row["geom"].y, row["geom"].x),
            })
        logger.debug(
            "cctv 원본 %d개를 위치 %d개로 집계",
            len(gdf),
            len(records),
        )
        return records
    
    # TAAS API 경로, 현재 미사용 — accident_collector.py의 CSV 기반 경로로 대체됨
    def build_accident_records(self) -> list:
        gdf = self.public.get("type", "accident_zone")
        records = []
        for _, row in gdf.iterrows():
            records.append({
                "csv_raw_id":    None,
                "public_raw_id": row.get("public_raw_id"),
                "safety_type":   "accident_zone",
                "purpose":       None,
                "geom":          CollectorUtils.make_point(row["geom"].y, row["geom"].x),
            })
        return records

    # TAAS API 경로, 현재 미사용 — accident_collector.py의 CSV 기반 경로로 대체됨
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
        streetlamp = self.build_streetlamp_records()
        security_light = self.build_security_light_records()
        records = streetlight + cctv + streetlamp + security_light
        logger.info(
            "safety_layer %d개 저장 시작 "
            "(streetlight=%d, cctv=%d, streetlamp=%d, security_light=%d)",
            len(records), len(streetlight), len(cctv),
            len(streetlamp), len(security_light),
        )
        SafetyRepository.save_all(records)

    def update_edge(self) -> None:
        """
        safety_score = CCTV(설치목적 필터 적용)·security_light 반경 20m 버퍼 커버리지 비율.
        이미 0.0~1.0 비율이라 CollectorUtils.update_edge_scores의 log 정규화를 거치지 않고
        그대로 기록한다.
        """
        EdgeRepository.ensure_score_column("safety_score")
        coverage = SafetyRepository.get_safety_coverage_by_edge()
        EdgeRepository.update_scores(
            [{"link_id": link_id, "safety_score": ratio} for link_id, ratio in coverage.items()]
        )

    def save(self) -> None:
        self.update_node()
        self.update_edge()


if __name__ == "__main__":
    collector = SafetyCollector()
    collector.save()
