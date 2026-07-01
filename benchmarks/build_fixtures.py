import logging

import pandas as pd

from benchmarks.config import ROUTE_NODES_PARQUET, ROUTE_EDGES_PARQUET, FIXTURES_DIR
from src.repository.network.graph_repository import GraphRepository

logger = logging.getLogger(__name__)


def build_route_fixture():
    """
    서울시 전역 도보 그래프를 빌드합니다.
    """
    logger.info("서울 전역 도보 그래프 로드 시작...")
    G = GraphRepository.load_graph()
    logger.info("로드 완료: 노드 %d, 엣지 %d", G.number_of_nodes(), G.number_of_edges())

    # 노드 → DataFrame (필요한 속성만 유지)
    node_keep = ["lat", "lon"]
    nodes_df = (
        pd.DataFrame([{"node_id": n, **{k: d.get(k) for k in node_keep}} for n, d in G.nodes(data=True)])
        .sort_values("node_id")
        .reset_index(drop=True)
    )

    # 엣지 → DataFrame (필요한 속성만 유지)
    edge_keep = ["link_id", "length", "safety_score", "nature_score", "landmark_score", "child_score"]
    edges_df = (
        pd.DataFrame(
            [{"u": u, "v": v, **{k: d.get(k) for k in edge_keep}} for u, v, d in G.edges(data=True)]
        )
        .sort_values(["u", "v"])
        .reset_index(drop=True)
    )

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    nodes_df.to_parquet(ROUTE_NODES_PARQUET, index=False)  # 노드 빌드
    edges_df.to_parquet(ROUTE_EDGES_PARQUET, index=False)  # 엣지 빌드

    logger.info(
        "fixture 저장 완료: nodes=%s (%d행), edges=%s (%d행)",
        ROUTE_NODES_PARQUET, len(nodes_df), ROUTE_EDGES_PARQUET, len(edges_df),
    )

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] [%(name)s] %(message)s")
    build_route_fixture()
