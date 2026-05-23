import math
import pandas as pd
import asyncio
from typing import List
from geoalchemy2.elements import WKTElement

from src.client.kakao_client import KakaoClient
from src.repository.poi_repository import LandmarkRepository
from src.repository.edge_repository import EdgeRepository
from src.repository.node_repository import NodeRepository


class LandmarkCollector(KakaoClient):
    def __init__(self):
        self.url = "https://docs.google.com/spreadsheets/d/1h4PPOJ6qSIBRghrqn0cXT-UrlToyMIM-NTSNtATF0gc/export?format=csv&hl=ko&gid=0#gid=0"
        self.data = self.load_data()

    def load_data(self):
        """
        데이터를 로드합니다.
        """
        return pd.read_csv(self.url)

    async def get_location(self, keyword: str):
        """
        kakao client를 통해 랜드마크의 정확한 위치를 조회합니다.
        """
        res = await self.get_address_from_keyword.ainvoke({
            "keyword": keyword,
            "lat": 37.5665,
            "lon": 126.9780
        })

        docs = res.get("documents")

        return [
            {
                "id": idx,
                "category_name": doc.get("category_name"),
                "place_name": doc.get("place_name"),
                "lat": doc.get("y"),
                "lon": doc.get("x")
            } for idx, doc in enumerate(docs)
        ]

    def select(self, landmark_candidate: List[dict]):
        """
        랜드마크의 후보군 중 1개를 택합니다.
        """
        print("랜드마크 후보군")
        for c in landmark_candidate:
            print(c)

        idx = int(input("번호 선택: "))
        selection = landmark_candidate[idx]
        print(f"선택한 랜드마크: {selection}")

        return selection

    def node_update(self, selections: List[dict]):
        """
        landmark 데이터를 기반으로 node를 업데이트합니다.
        """
        base_id = NodeRepository.get_max_node_id()
        nodes = [
            {
                "node_id": base_id + i + 1,
                "node_type": "landmark",
                "is_underground": False,
                "is_overpass": False,
                "geom": selection["geom"]
            }
            for i, selection in enumerate(selections)
        ]
        NodeRepository.save_all(nodes)

        name_to_node_id = {
            selections[i]["name"]: base_id + i + 1
            for i in range(len(selections))
        }
        LandmarkRepository.update_walk_node_ids(name_to_node_id)

    def edge_update(self):
        """
        랜드마크 데이터를 기반으로 edge를 업데이트합니다.
        """
        landmark_h3_counts = LandmarkRepository.get_landmark_h3_counts()  # h3 cell별 랜드마크 개수
        edge_h3_rows = EdgeRepository.get_link_h3_cells()  # 도보: h3 cell

        if not edge_h3_rows:
            print("walk_edges 데이터 없음")
            return
        
        # 도보별 랜드마크 개수 매핑
        landmark_log = [math.log(landmark_h3_counts.get(row.h3_cell, 0) + 1) for row in edge_h3_rows]
        landmark_max = max(landmark_log) or 1.0

        updates = [
            {
                "link_id": row.link_id,
                "landmark_score": 1.0 + landmark_log[i] / landmark_max,  # 1 ~ 2
            }
            for i, row in enumerate(edge_h3_rows)
        ]

        EdgeRepository.update_scores(updates)

    async def save(self):
        """
        개별 랜드마크를 저장하고, node 및 edge를 업데이트합니다.
        """
        selections = []
        for _, row in self.data.iterrows():
            landmark_candidate = await self.get_location(row["name"])
            selection = self.select(landmark_candidate)

            selections.append({
                "name": selection.get("place_name"),
                "geom": WKTElement(f"POINT({selection.get('lon')} {selection.get('lat')})", srid=4326)
            })

        print("\n최종")
        for s in selections:
            print(s)

        LandmarkRepository.save_all(selections)
        self.node_update(selections)
        EdgeRepository.ensure_score_column("landmark_score")
        self.edge_update()

if __name__ == "__main__":
    collector = LandmarkCollector()
    asyncio.run(collector.save())
