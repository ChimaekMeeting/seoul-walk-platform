import math

from src.repository.network.edge_repository import EdgeRepository
from src.repository.layer.nature_repository import NatureRepository
from src.repository.layer.safety_repository import SafetyRepository


class ScoreCalculator:

    @staticmethod
    def calculate_scores() -> None:
        """
        safety_layer(safety_score) 및 poi_layer(nature_score) 기반으로
        walk_edges의 안전·자연 점수를 계산하고 업데이트합니다.
        """
        edge_h3_rows = EdgeRepository.get_link_h3_cells()
        if not edge_h3_rows:
            print("walk_edges 데이터 없음")
            return

        safety_h3_counts = SafetyRepository.get_safety_h3_counts()
        nature_h3_counts = NatureRepository.get_nature_h3_counts()

        safety_log = [math.log(safety_h3_counts.get(row.h3_cell, 0) + 1) for row in edge_h3_rows]
        nature_log = [math.log(nature_h3_counts.get(row.h3_cell, 0) + 1) for row in edge_h3_rows]

        safety_max = max(safety_log) or 1.0
        nature_max = max(nature_log) or 1.0

        updates = [
            {
                "link_id":      row.link_id,
                "safety_score": 1.0 + safety_log[i] / safety_max,
                "nature_score": 1.0 + nature_log[i] / nature_max,
            }
            for i, row in enumerate(edge_h3_rows)
        ]

        EdgeRepository.update_scores(updates)
        print(f"[완료] {len(updates)}개 엣지 score 업데이트")


if __name__ == "__main__":
    ScoreCalculator.calculate_scores()
