import asyncio

import pandas as pd

from src.infrastructure.external.client.kakao_client import KakaoClient
from src.data.utils import CollectorUtils
from src.repository.network.edge_repository import EdgeRepository
from src.repository.layer.landmark_repository import LandmarkRepository


class LandmarkCollector:
    """
    Google Sheets의 랜드마크 목록을 Kakao API로 조회하여 landmark_layer와 walk_nodes에 저장하고
    walk_edges.landmark_score를 업데이트합니다.
    """
    def __init__(self):
        self.kakao_client = KakaoClient()

        self.SHEET_URL = (
            "https://docs.google.com/spreadsheets/d/"
            "1h4PPOJ6qSIBRghrqn0cXT-UrlToyMIM-NTSNtATF0gc/export?format=csv&hl=ko&gid=0#gid=0"
        )
        self.data = self.load_data()

    def load_data(self) -> pd.DataFrame:
        """
        랜드마크 목록을 Google Sheets CSV로 로드합니다.
        """
        return pd.read_csv(self.SHEET_URL)

    async def get_location(self, keyword: str) -> list[dict]:
        """
        Kakao 키워드 검색으로 장소 후보 목록을 반환합니다.
        """
        res = await self.kakao_client.get_address_from_keyword(
            keyword=keyword,
            lat=37.5665,
            lon=126.9780,
        )
        docs = res.get("documents")
        return [
            {
                "id":            idx,
                "category_name": doc.get("category_name"),
                "place_name":    doc.get("place_name"),
                "lat":           doc.get("y"),
                "lon":           doc.get("x"),
            }
            for idx, doc in enumerate(docs)
        ]

    def select(self, candidates: list[dict]) -> dict:
        """
        후보 장소 목록을 출력하고 사용자 입력으로 랜드마크 1개를 선택합니다.
        """
        for c in candidates:
            print(c)
        idx = int(input("번호 선택: "))
        return candidates[idx]

    def update_node(self, selections: list[dict]) -> None:
        """
        landmark_layer에 저장하고 선택된 위치를 walk_nodes에 등록합니다.
        """
        LandmarkRepository.save_all(selections)
        name_to_node_id = CollectorUtils.register_nodes(selections, node_type="landmark")
        LandmarkRepository.update_walk_node_ids(name_to_node_id)

    def update_edge(self) -> None:
        """
        랜드마크 밀도 기반으로 walk_edges.landmark_score를 업데이트합니다.
        """
        EdgeRepository.ensure_score_column("landmark_score")
        CollectorUtils.update_edge_scores("landmark_score", LandmarkRepository.get_landmark_h3_counts())

    async def save(self) -> None:
        """
        랜드마크를 조회·선택한 뒤 landmark_layer·walk_nodes를 저장하고 walk_edges를 업데이트합니다.
        """
        selections = []
        for _, row in self.data.iterrows():
            candidates = await self.get_location(row["name"])
            selection = self.select(candidates)
            selections.append({
                "name": selection.get("place_name"),
                "geom": CollectorUtils.make_point(
                    float(selection.get("lat")),
                    float(selection.get("lon")),
                ),
            })

        self.update_node(selections)
        self.update_edge()


if __name__ == "__main__":
    collector = LandmarkCollector()
    asyncio.run(collector.save())
