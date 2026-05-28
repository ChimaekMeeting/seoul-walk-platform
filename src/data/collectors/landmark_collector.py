import asyncio
from typing import List

import pandas as pd

from src.infrastructure.external.client.kakao_client import KakaoClient
from src.data.utils import CollectorUtils
from src.repository.network.edge_repository import EdgeRepository
from src.repository.layer.landmark_repository import LandmarkRepository


class LandmarkCollector:
    def __init__(self):
        self.kakao_client = KakaoClient()
        self.url = "https://docs.google.com/spreadsheets/d/1h4PPOJ6qSIBRghrqn0cXT-UrlToyMIM-NTSNtATF0gc/export?format=csv&hl=ko&gid=0#gid=0"
        self.data = self.load_data()

    def load_data(self):
        """
        랜드마크 목록을 Google Sheets에서 로드합니다.
        """
        return pd.read_csv(self.url)

    async def get_location(self, keyword: str):
        """
        Kakao API로 키워드에 해당하는 장소 후보를 조회합니다.
        """
        print(keyword)
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

    def select(self, landmark_candidate: List[dict]):
        """
        후보 장소 목록에서 랜드마크 1개를 사용자가 선택합니다.
        """
        print("랜드마크 후보군")
        for c in landmark_candidate:
            print(c)
        idx = int(input("번호 선택: "))
        selection = landmark_candidate[idx]
        print(f"선택한 랜드마크: {selection}")
        return selection

    def update_node(self, selections):
        """
        랜드마크 위치를 walk_nodes에 등록하고 walk_node_id를 업데이트합니다.
        """
        name_to_node_id = CollectorUtils.register_nodes(selections, node_type="landmark")
        LandmarkRepository.update_walk_node_ids(name_to_node_id)

    def update_edge(self):
        """
        랜드마크 밀도 기반으로 walk_edges.landmark_score를 업데이트합니다.
        """
        EdgeRepository.ensure_score_column("landmark_score")
        CollectorUtils.update_edge_scores("landmark_score", LandmarkRepository.get_landmark_h3_counts())

    async def save(self):
        """
        랜드마크를 조회·저장하고 node와 edge를 업데이트합니다.
        """
        selections = []
        for _, row in self.data.iterrows():
            landmark_candidate = await self.get_location(row["name"])
            selection = self.select(landmark_candidate)
            selections.append({
                "name": selection.get("place_name"),
                "geom": CollectorUtils.make_point(
                    float(selection.get("lat")),
                    float(selection.get("lon")),
                ),
            })

        LandmarkRepository.save_all(selections)

        self.update_node(selections)
        self.update_edge()


if __name__ == "__main__":
    collector = LandmarkCollector()
    asyncio.run(collector.save())
