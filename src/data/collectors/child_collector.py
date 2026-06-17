import asyncio
import os
import httpx
import pandas as pd
from dotenv import load_dotenv

from src.data.utils.collector_utils import CollectorUtils
from src.repository.layer.child_repository import ChildRepository
from src.repository.network.edge_repository import EdgeRepository

load_dotenv()

class ChildCollector:
    """
    어린이보호구역(CSV)과 어린이놀이시설(공공데이터 API) 데이터를 child_layer에 저장합니다.
    서울 소재 + 운영 중인 시설만 저장합니다.
    """
    def __init__(self):
        self.protection_zones = self.load_protection_zones()
        self.clean_protection_zones()
        self.play_facilities = pd.DataFrame(asyncio.run(self.load_play_facilities()))

    def load_protection_zones(self) -> pd.DataFrame:
        """
        어린이보호구역 데이터를 로드합니다.
        """
        try:
            return pd.read_csv("src/data/raw/전국어린이보호구역표준데이터.csv", encoding="cp949")
        except UnicodeDecodeError:
            return pd.read_csv("src/data/raw/전국어린이보호구역표준데이터.csv", encoding="utf-8")
        except FileNotFoundError:
            print("전국어린이보호구역표준데이터.csv가 없습니다. 공공데이터포털에서 다운로드해주세요.")

    def clean_protection_zones(self):
        """
        어린이보호구역 데이터를 정제합니다.
        """
        self.protection_zones = self.protection_zones[["대상시설명", "소재지도로명주소", "위도", "경도"]]
        self.protection_zones.dropna(inplace=True, ignore_index=True)
        self.protection_zones.drop_duplicates(["위도", "경도"], ignore_index=True)

        self.protection_zones["is_seoul"] = self.protection_zones.apply(lambda x: "서울" in x["소재지도로명주소"], axis=1)
        self.protection_zones = self.protection_zones[self.protection_zones["is_seoul"] == True].reset_index(drop=True)
        self.protection_zones = self.protection_zones.drop(columns=["is_seoul"], inplace=True)

    async def load_play_facilities(self) -> list[dict]:
        """
        어린이놀이시설 데이터를 로드합니다.
        """
        url = "https://apis.data.go.kr/1741000/pfc3/getPfctInfo3"
        params = {
            "serviceKey": os.getenv("PUBLIC_DATA_API_KEY"),
            "recordCountPerPage": 1000,
        }

        results = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            for i in range(1, 87):
                params["pageIndex"] = i

                response = await client.get(url=url, params=params)
                data = response.json().get("response").get("body").get("items")

                results.extend([{
                    "name": d.get("pfctNm"),
                    "category": "어린이놀이시설",
                    "address": d.get("ronaAddr"),
                    "lat": float(d.get("latCrtsVl")),
                    "lon": float(d.get("lotCrtsVl")),
                } for d in data if self.clean_play_facilities(d)])

        return results

    def clean_play_facilities(self, row: dict) -> bool:
        """
        서울에 위치하고 현재 운영 중인 어린이놀이시설만을 필터링합니다.
        """
        if row.get("pfctNm") not in (None, "") \
        and row.get("ronaAddr") not in (None, "") \
        and row.get("lotCrtsVl") not in (None, "") \
        and row.get("latCrtsVl") not in (None, "") \
        and row.get("operYnCdNm") == "운영" \
        and "서울" in row.get("ronaAddr"):
            return True
            
        return False

    def update_node(self, records: list[dict]) -> None:
        """
        어린이보호구역, 어린이놀이시설 Node를 저장합니다.
        """
        ChildRepository.save_all(records)

    def update_edge(self) -> None:
        """
        어린이보호구역, 어린이놀이시설 데이터를 반영하여 Edge를 업데이트합니다.
        """
        EdgeRepository.ensure_score_column("child_score")
        CollectorUtils.update_edge_scores("child_score", ChildRepository.get_child_h3_counts())

    def save(self) -> None:
        """
        어린이보호구역, 어린이놀이시설 데이터를 저장합니다.
        """
        records = []

        for _, row in self.protection_zones.iterrows():
            records.append({
                "name": row["대상시설명"],
                "category": "어린이보호구역",
                "address": row["소재지도로명주소"],
                "geom": CollectorUtils.make_point(float(row["위도"]), float(row["경도"])),
            })

        for _, row in self.play_facilities.iterrows():
            records.append({
                "name": row["name"],
                "category": row["category"],
                "address": row["address"],
                "geom": CollectorUtils.make_point(float(row["lat"]), float(row["lon"])),
            })

        self.update_node(records)
        self.update_edge()
