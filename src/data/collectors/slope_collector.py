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

    # _slope_to_score()가 staticmethod라 클래스 속성으로 둔다.
    # (인스턴스 속성으로만 두면 SlopeCalculator.* 참조가 실패한다)
    #
    # THRESHOLD_PCT [문헌] 「장애인·노인·임산부 등의 편의증진 보장에 관한 법률 시행규칙」의
    #                     경사로 기울기 상한 1/12(≈8.33%). 이 이하는 감점하지 않는다.
    #                     서울 도보 엣지 278,762개 중 39,171개(14.1%)가 이 값을 초과한다.
    # MAX_SLOPE_PCT [실측] 서울 도보망 경사 분포의 p95(16.35%). 이 이상은 최대 페널티.
    #                     (분포: p50 1.47 / p75 4.72 / p90 10.73 / p95 16.35 / p99 33.49)
    THRESHOLD_PCT = 8.3333
    MAX_SLOPE_PCT = 16.35

    def __init__(self):
        self._elevations: dict = {}

        self.DEM_PATH   = os.getenv("DEM_PATH", "src/data/raw/dem/한반도90m_GRS80.img")
        self.BATCH_SIZE = 5000

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
            # rasterio.sample()은 밴드 배열을 돌려준다. NumPy 2부터 크기 1이어도
            # 1차원 배열을 float()로 직접 변환할 수 없으므로 첫 원소를 꺼내 쓴다.
            val = float(np.ravel(elev_arr)[0])
            elevations[node_id] = (
                None if (nodata is not None and val == nodata) or np.isnan(val) else val
            )
        return elevations

    @staticmethod
    def _slope_to_score(slope_pct: float) -> float:
        """
        경사율(%)을 0.0~1.0 범위의 slope_score로 변환합니다. 1.0이 가장 평탄합니다.

        THRESHOLD_PCT 이하는 보행 부담의 차이가 유의하지 않다고 보아 감점하지 않고,
        그 위로 MAX_SLOPE_PCT까지 선형으로 감점합니다. 계단식이 아니라 비례식이므로
        임계값 바로 근처에서 점수가 급변하지 않습니다.
        """
        threshold = SlopeCalculator.THRESHOLD_PCT
        cap       = SlopeCalculator.MAX_SLOPE_PCT
        if slope_pct <= threshold:
            return 1.0
        if slope_pct >= cap:
            return 0.0
        return round(1.0 - (slope_pct - threshold) / (cap - threshold), 6)

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
        NodeRepository.update_elevations(self._elevations)
        logger.info(
            "elevation_m 저장 완료: %d개 (고도 없음 %d개)",
            sum(1 for v in self._elevations.values() if v is not None),
            sum(1 for v in self._elevations.values() if v is None),
        )

    def update_edge(self) -> None:
        """
        노드 고도값으로 walk_edges.slope_score를 계산하고 저장합니다.
        """
        # walk_edges 점수 컬럼이 축소되면서 slope_score가 기본 스키마에서 빠졌으므로
        # SafetyCollector와 동일하게 컬럼 존재를 먼저 보장한다.
        EdgeRepository.ensure_score_column("slope_score")
        updates = self.calculate_edge_slopes()
        # update_slope_scores_batch()는 엣지 1건마다 UPDATE를 실행해 27만 건에 수 분이 걸린다.
        # 같은 저장소의 update_scores()가 unnest 기반 일괄 UPDATE라 훨씬 빠르다.
        EdgeRepository.update_scores(updates)
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
