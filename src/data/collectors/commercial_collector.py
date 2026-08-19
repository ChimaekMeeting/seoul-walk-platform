import logging

from src.data.sources.csv_source import CSVSource
from src.data.utils.collector_utils import CollectorUtils
from src.repository.layer.commercial_repository import CommercialRepository
from src.repository.network.edge_repository import EdgeRepository

logger = logging.getLogger(__name__)


class CommercialCollector:
    """상권 위치를 Edge 반경 기준으로 집계해 제한된 편의 점수를 생성합니다."""

    def __init__(self, csv_source: CSVSource | None = None):
        self.csv = csv_source or CSVSource()

    def save(self) -> None:
        self.csv.get("type", "commercial")
        EdgeRepository.ensure_score_column("convenience_score")
        edge_counts = CommercialRepository.get_commercial_counts_by_edge()
        CollectorUtils.update_edge_scores("convenience_score", edge_counts)
        logger.info("상권 편의 점수 반영 Edge %d개", len(edge_counts))
