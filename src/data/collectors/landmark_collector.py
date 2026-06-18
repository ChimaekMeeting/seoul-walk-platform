import asyncio

import pandas as pd

from src.data.sources.csv_source import CSVSource
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
        self.csv = CSVSource()

        self.SHEET_URL = (
            "https://docs.google.com/spreadsheets/d/"
            "1h4PPOJ6qSIBRghrqn0cXT-UrlToyMIM-NTSNtATF0gc/export?format=csv&hl=ko&gid=0#gid=0"
        )
        self.data = self.csv.load_landmark_sheet(self.SHEET_URL)

    async def get_location(self, keyword: str) -> list[dict]:
        res = await self.kakao_client.get_address_from_keyword(
            keyword=keyword,
            lat=37.5665,
            lon=126.9780,
        )
        docs = res.documents
        return [
            {
                "id":            idx,
                "category_name": doc.category_name,
                "place_name":    doc.place_name,
                "lat":           doc.y,
                "lon":           doc.x,
            }
            for idx, doc in enumerate(docs)
        ]

    def select(self, candidates: list[dict]) -> dict:
        for c in candidates:
            print(c)
        idx = int(input("번호 선택: "))
        return candidates[idx]

    def update_node(self, selections: list[dict]) -> None:
        LandmarkRepository.save_all(selections)
        name_to_node_id = CollectorUtils.register_nodes(selections, node_type="landmark")
        LandmarkRepository.update_walk_node_ids(name_to_node_id)

    def update_edge(self) -> None:
        EdgeRepository.ensure_score_column("landmark_score")
        CollectorUtils.update_edge_scores("landmark_score", LandmarkRepository.get_landmark_h3_counts())

    async def save(self) -> None:
        if LandmarkRepository.is_populated():
            print("  ⏭️  landmark_layer 이미 적재됨, 스킵")
            return
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
