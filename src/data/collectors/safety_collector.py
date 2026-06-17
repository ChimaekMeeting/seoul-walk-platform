import pandas as pd

from src.data.utils import CollectorUtils
from src.repository.network.edge_repository import EdgeRepository
from src.repository.layer.safety_repository import SafetyRepository


class SafetyCollector:
    """
    스마트 가로등과 CCTV 데이터를 파싱하여 safety_layer에 저장하고 walk_edges.safety_score를 업데이트합니다.
    """
    def __init__(self):
        self.data = self.load_data()

    def load_data(self) -> dict:
        """
        가로등 CSV와 CCTV 엑셀 파일을 로드합니다.
        """
        return {
            "streetlight": pd.read_csv("src/data/raw/전국스마트가로등표준데이터.csv", encoding="cp949"),
            "cctv":        pd.read_excel("src/data/raw/서울시CCTV정보.xlsx"),
        }

    def build_streetlight_records(self) -> list:
        """
        서울시 스마트 가로등 데이터를 파싱하여 safety_layer INSERT용 dict 리스트를 반환합니다.
        """
        df = self.data["streetlight"]
        seoul = df[df["시도명"].str.contains("서울", na=False)]
        records = []
        for _, row in seoul.iterrows():
            if pd.isna(row["경도"]) or pd.isna(row["위도"]):
                continue
            records.append({
                "safety_type": "streetlight",
                "address":     str(row["소재지도로명주소"]) if pd.notna(row.get("소재지도로명주소")) else "",
                "geom":        CollectorUtils.make_point(row["위도"], row["경도"]),
            })
        return records

    def build_cctv_records(self) -> list:
        """
        서울시 CCTV 데이터를 파싱하여 safety_layer INSERT용 dict 리스트를 반환합니다.
        """
        df = self.data["cctv"]
        records = []
        for _, row in df.iterrows():
            if pd.isna(row["WGS84경도"]) or pd.isna(row["WGS84위도"]):
                continue
            records.append({
                "safety_type": "cctv",
                "address":     str(row["소재지도로명주소"]) if pd.notna(row.get("소재지도로명주소")) else "",
                "geom":        CollectorUtils.make_point(row["WGS84위도"], row["WGS84경도"]),
            })
        return records

    def update_node(self) -> None:
        """
        safety_layer를 초기화하고 가로등·CCTV POI를 저장합니다.
        """
        SafetyRepository.save_all(self.build_streetlight_records() + self.build_cctv_records())

    def update_edge(self) -> None:
        """
        안전 시설물 밀도 기반으로 walk_edges.safety_score를 업데이트합니다.
        """
        EdgeRepository.ensure_score_column("safety_score")
        CollectorUtils.update_edge_scores("safety_score", SafetyRepository.get_safety_h3_counts())

    def save(self) -> None:
        """
        safety_layer를 저장한 뒤 walk_edges.safety_score를 업데이트합니다.
        """
        self.update_node()
        self.update_edge()


if __name__ == "__main__":
    collector = SafetyCollector()
    collector.save()
