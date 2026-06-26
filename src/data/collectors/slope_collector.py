import logging
import os

import numpy as np

from src.repository.network.node_repository import NodeRepository
from src.repository.network.edge_repository import EdgeRepository

logger = logging.getLogger(__name__)


class SlopeCalculator:
    """
    DEM 래스터를 이용해 walk_nodes의 고도를 샘플링하고 walk_edges.slope_score를 업데이트합니다.
    """
    def __init__(self):
        self._elevations: dict = {}

        self.DEM_PATH      = os.getenv("DEM_PATH", "src/data/raw/dem/한반도90m_GRS80.img")
        self.MAX_SLOPE_PCT = 10.0
        self.BATCH_SIZE    = 5000

    def get_node_elevations(self) -> dict:
        """
        walk_nodes 좌표를 rasterio.sample()로 배치 샘플링하여 {node_id: elevation_m} 딕셔너리를 반환합니다.
        좌표 범위 밖이거나 nodata인 노드는 None으로 처리합니다.
        """
        import rasterio
        from pyproj import Transformer

        rows = NodeRepository.get_all_coordinates()
        if not rows:
            raise RuntimeError("walk_nodes가 비어있습니다. 네트워크를 먼저 적재하세요.")

        with rasterio.open(self.DEM_PATH) as dataset:
            transformer = Transformer.from_crs("EPSG:4326", dataset.crs, always_xy=True)
            node_ids   = [r.node_id for r in rows]
            coords_dem = [transformer.transform(r.lon, r.lat) for r in rows]

            x0, y0 = coords_dem[0]
            b = dataset.bounds
            if not (b.left < x0 < b.right and b.bottom < y0 < b.top):
                raise RuntimeError("좌표 변환 실패. DEM 범위를 벗어났습니다.")

            nodata  = dataset.nodata
            sampled = list(dataset.sample(coords_dem, indexes=1))

        elevations = {}
        for node_id, elev_arr in zip(node_ids, sampled):
            val = float(elev_arr)
            elevations[node_id] = (
                None if (nodata is not None and val == nodata) or np.isnan(val) else val
            )
        return elevations

    @staticmethod
    def _slope_to_score(slope_pct: float) -> float:
        """
        경사율(%)을 0.0~1.0 범위의 slope_score로 변환합니다.
        """
        return max(0.0, round(1.0 - slope_pct / SlopeCalculator.MAX_SLOPE_PCT, 6))

    def calculate_edge_slopes(self) -> list:
        """
        저장된 노드 고도값으로 엣지별 slope_score를 계산하여 업데이트 dict 목록을 반환합니다.
        고도 정보가 없는 엣지는 중립값 0.5로 처리합니다.
        """
        edges = EdgeRepository.get_all_for_slope()
        if not edges:
            raise RuntimeError("walk_edges가 비어있습니다.")

        updates = []
        for edge in edges:
            elev_start = self._elevations.get(edge.start_node)
            elev_end   = self._elevations.get(edge.end_node)
            if elev_start is None or elev_end is None:
                score = 0.5
            else:
                elev_diff = abs(elev_end - elev_start)
                slope_pct = (elev_diff / max(edge.length_m or 1.0, 1.0)) * 100.0
                score = self._slope_to_score(slope_pct)
            updates.append({"link_id": edge.link_id, "slope_score": score})
        return updates

    def update_node(self) -> None:
        """
        walk_nodes 좌표를 DEM으로 샘플링하여 노드별 고도값을 계산합니다.
        """
        self._elevations = self.get_node_elevations()

    def update_edge(self) -> None:
        """
        노드 고도값으로 walk_edges.slope_score를 계산하고 저장합니다.
        """
        updates = self.calculate_edge_slopes()
        EdgeRepository.update_slope_scores_batch(updates, batch_size=self.BATCH_SIZE)
        logger.info("slope_score 업데이트 완료: %d개", len(updates))

    def save(self) -> None:
        """
        고도 샘플링 후 walk_edges.slope_score를 업데이트합니다.
        """
        self.update_node()
        self.update_edge()


if __name__ == "__main__":
    calculator = SlopeCalculator()
    calculator.save()
