import logging

from src.data.sources.public_source import PublicSource
from src.data.utils.collector_utils import CollectorUtils
from src.repository.layer.landmark_repository import LandmarkRepository
from src.repository.network.edge_repository import EdgeRepository

logger = logging.getLogger(__name__)


class LandmarkCollector:
    """
    TourAPI(한국관광공사)에서 서울 관광지·문화시설 데이터를 수집하여
    landmark_layer에 저장하고 walk_edges.landmark_score를 업데이트합니다.
    """

    def __init__(self):
        self.public = PublicSource()

    def build_records(self) -> list[dict]:
        gdf = self.public.get("type", "landmark")
        records = [
            {
                "name": row["name"],
                "geom": CollectorUtils.make_point(row["geom"].y, row["geom"].x),
            }
            for _, row in gdf.iterrows()
            if row.get("name")
        ]
        logger.debug("랜드마크 레코드 %d개 빌드", len(records))
        return records

    def update_node(self) -> None:
        records = self.build_records()
        if not records:
            logger.warning("수집된 랜드마크 데이터가 없습니다.")
            return
        LandmarkRepository.save_all(records)
        logger.info("landmark_layer %d개 저장 완료", len(records))

    def update_edge(self) -> None:
        EdgeRepository.ensure_score_column("landmark_score")
        CollectorUtils.update_edge_scores("landmark_score", LandmarkRepository.get_landmark_counts_by_edge())

    def save(self) -> None:
        self.update_node()
        self.update_edge()


if __name__ == "__main__":
    LandmarkCollector().save()
