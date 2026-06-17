import math
from typing import Optional

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, MultiLineString

from src.data.utils import CollectorUtils
from src.repository.layer.running_repository import RunningRepository
from src.repository.network.edge_repository import EdgeRepository


# ──────────────────────────────────────────────────────────────
# 하천변 데이터
# ──────────────────────────────────────────────────────────────

RIVER_COURSES: list[dict] = [
    {"name": "한강 반포 구간",       "course_type": "river", "distance_m": 6_400,  "difficulty": "easy",   "start_lat": 37.5121, "start_lon": 126.9994},
    {"name": "한강 여의도 순환 코스", "course_type": "river", "distance_m": 7_000,  "difficulty": "easy",   "start_lat": 37.5285, "start_lon": 126.9326},
    {"name": "청계천 전 구간",        "course_type": "river", "distance_m": 10_920, "difficulty": "easy",   "start_lat": 37.5700, "start_lon": 126.9784},
    {"name": "안양천 서울 구간",      "course_type": "river", "distance_m": 12_000, "difficulty": "easy",   "start_lat": 37.5270, "start_lon": 126.8560},
    {"name": "중랑천 전 구간",        "course_type": "river", "distance_m": 15_000, "difficulty": "medium", "start_lat": 37.6490, "start_lon": 127.0760},
]

RUNNING_PARK_CONFIG: dict[str, dict] = {
    "올림픽공원":               {"difficulty_override": "easy"},
    "보라매공원":               {"difficulty_override": "easy"},
    "서울숲":                   {"difficulty_override": "easy"},
    "월드컵공원":               {"difficulty_override": "medium"},
    "북서울꿈의숲":             {"difficulty_override": None},
    "남산공원":                 {"difficulty_override": "medium"},
    "용산가족공원":             {"difficulty_override": "easy"},
    "어린이대공원":             {"difficulty_override": "easy"},
    "천호근린공원":             {"difficulty_override": "easy"},
    "여의도근린공원":           {"difficulty_override": "easy"},
    "송파나루근린공원(석촌호수)": {"difficulty_override": "easy"},
    "선유도근린공원":           {"difficulty_override": "easy"},
    "노량진공원":               {"difficulty_override": "easy"},
    "손기정체육공원":           {"difficulty_override": "easy"},
    "서서울호수공원":           {"difficulty_override": "easy"},
}

_TRAIL_COORDS: dict[str, tuple[float, float]] = {
    "수락산":     (37.6895, 127.0465),
    "덕릉고개":   (37.6541, 127.0722),
    "불암산":     (37.6620, 127.0800),
    "용마산":     (37.6218, 127.0964),
    "아차산":     (37.5830, 127.0958),
    "고덕산":     (37.5491, 127.1020),
    "일자산":     (37.5475, 127.1421),
    "탄천":       (37.5019, 127.1248),
    "구룡산":     (37.4849, 127.1004),
    "우면산":     (37.4705, 127.0421),
    "관악산":     (37.4773, 126.9818),
    "호암산":     (37.4724, 126.9637),
    "안양천 상류": (37.4630, 126.9020),
    "안양천 하류": (37.5032, 126.8685),
    "하늘공원":   (37.5616, 126.8640),
    "앵봉산":     (37.5961, 126.8890),
    "북한산 은평": (37.6268, 126.9188),
    "북한산 종로": (37.6465, 126.9555),
    "북한산 성북": (37.6371, 126.9706),
    "북한산 강북": (37.6397, 127.0108),
    "북한산 도봉": (37.6616, 127.0155),
}


# ──────────────────────────────────────────────────────────────
# 헬퍼 함수
# ──────────────────────────────────────────────────────────────

def _classify_difficulty(distance_m: Optional[float]) -> str:
    """
    거리(미터) 기반으로 난이도를 분류합니다.
    """
    if distance_m is None or distance_m < 5_000:
        return "easy"
    if distance_m < 10_000:
        return "medium"
    return "hard"


def _find_col(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    """
    DataFrame 컬럼 중 candidates 순서대로 첫 번째로 존재하는 컬럼명을 반환합니다.
    """
    for c in candidates:
        if c in df.columns:
            return c
    return None


# ──────────────────────────────────────────────────────────────
# Collector
# ──────────────────────────────────────────────────────────────

class RunningCourseCollector:
    """
    하천, 공원, 둘레길, 자전거도로 데이터를 수집하여 courses 테이블에 저장하고
    walk_edges.running_score를 H3 셀 기반으로 업데이트합니다.
    """
    def __init__(self):
        self.PARK_FILE     = "src/data/raw/서울시 주요 공원현황.xlsx"
        self.RIVER_GEOJSON = "src/data/raw/서울시 하천.geojson"
        self.BIKE_FILE     = "src/data/raw/서울시 자전거도로.csv"
        self.data = self.load_data()

    def load_data(self) -> dict:
        """
        파일 기반 데이터를 로드합니다. 파일이 없으면 None으로 처리합니다.
        """
        data: dict = {}

        try:
            df = pd.read_excel(self.PARK_FILE, header=1)
            df.columns = [str(c).strip() for c in df.columns]
            data["park"] = df
        except Exception:
            print(f"  ⚠️  파일 없음: {self.PARK_FILE}")
            data["park"] = None

        try:
            gdf = gpd.read_file(self.RIVER_GEOJSON)
            if gdf.crs and gdf.crs.to_epsg() != 4326:
                gdf = gdf.to_crs(epsg=4326)
            data["river_geojson"] = gdf
        except Exception:
            print(f"  ⚠️  파일 없음: {self.RIVER_GEOJSON}")
            data["river_geojson"] = None

        try:
            try:
                df = pd.read_csv(self.BIKE_FILE, encoding="cp949")
            except UnicodeDecodeError:
                df = pd.read_csv(self.BIKE_FILE, encoding="utf-8")
            df.columns = [str(c).strip() for c in df.columns]
            data["bike"] = df
        except Exception:
            print(f"  ⚠️  파일 없음: {self.BIKE_FILE}")
            data["bike"] = None

        return data

    def _make_record(
        self,
        name: str,
        course_type: str,
        lat: float,
        lon: float,
        distance_m: Optional[float] = None,
        difficulty: Optional[str] = None,
    ) -> dict:
        """
        courses INSERT용 dict를 생성합니다.
        """
        return {
            "name":        name,
            "course_type": course_type,
            "difficulty":  difficulty or _classify_difficulty(distance_m),
            "geom":        CollectorUtils.make_point(lat, lon),
        }

    def build_river_records(self) -> list:
        """
        하천변 코스 목록 데이터를 courses INSERT용 dict 목록으로 변환합니다.
        """
        return [
            self._make_record(
                name=item["name"],
                course_type=item["course_type"],
                lat=item["start_lat"],
                lon=item["start_lon"],
                distance_m=item.get("distance_m"),
                difficulty=item.get("difficulty"),
            )
            for item in RIVER_COURSES
        ]

    def build_park_records(self) -> list:
        """
        서울시 주요 공원 XLSX에서 런닝 적합 공원을 필터링하여 courses INSERT용 dict 목록을 반환합니다.
        """
        if self.data["park"] is None:
            return []

        def _is_running_park(name: str) -> bool:
            return any(k in str(name).strip() for k in RUNNING_PARK_CONFIG)

        records = []
        for _, row in self.data["park"][self.data["park"]["공원명"].apply(_is_running_park)].iterrows():
            lon = row.get("X좌표(WGS84)")
            lat = row.get("Y좌표(WGS84)")
            if pd.isna(lon) or pd.isna(lat):
                continue
            try:
                lat, lon = float(lat), float(lon)
            except (ValueError, TypeError):
                continue
            if not (37.4 <= lat <= 37.7 and 126.7 <= lon <= 127.2):
                continue

            park_name = str(row["공원명"]).strip()
            config = next(
                (v for k, v in RUNNING_PARK_CONFIG.items() if k in park_name),
                {"difficulty_override": None},
            )

            area_raw = str(row.get("면적", "")).replace(",", "")
            area_m2: Optional[float] = None
            for token in area_raw.split():
                try:
                    area_m2 = float(token.replace("㎡", "").replace("m²", ""))
                    break
                except ValueError:
                    continue

            dist_m = round(4 * math.sqrt(area_m2), 0) if area_m2 else None
            records.append(self._make_record(
                name=f"{park_name} 순환 코스",
                course_type="park",
                lat=lat,
                lon=lon,
                distance_m=dist_m,
                difficulty=config["difficulty_override"],
            ))
        return records

    def build_trail_records(self) -> list:
        """
        하천변 둘레길 좌표 데이터를 courses INSERT용 dict 목록으로 변환합니다.
        """
        return [
            self._make_record(
                name=f"{name} 둘레길",
                course_type="trail",
                lat=lat,
                lon=lon,
            )
            for name, (lat, lon) in _TRAIL_COORDS.items()
        ]

    def build_river_geojson_records(self) -> list:
        """
        서울시 하천 GeoJSON에서 시작 좌표를 추출하여 courses INSERT용 dict 목록을 반환합니다.
        """
        if self.data["river_geojson"] is None:
            return []

        gdf      = self.data["river_geojson"]
        name_col = _find_col(gdf, ["하천명", "RIVER_NM", "WATERBODY_NM", "HCH_NAME", "name:ko", "name", "NAME"])
        len_col  = _find_col(gdf, ["SHAPE_LEN", "길이", "연장", "구간거리", "LENGTH"])

        records = []
        for _, row in gdf.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            if isinstance(geom, MultiLineString):
                geom = max(geom.geoms, key=lambda g: g.length)
            if not isinstance(geom, LineString):
                continue

            s_lon, s_lat = geom.coords[0][:2]
            if not (37.4 <= s_lat <= 37.7 and 126.7 <= s_lon <= 127.2):
                continue

            name = str(row[name_col]).strip() if name_col and str(row[name_col]) != "nan" else "하천"

            dist_m: Optional[float] = None
            if len_col:
                try:
                    val = float(row[len_col])
                    dist_m = val if val >= 1.0 else val * 111_000
                except (ValueError, TypeError):
                    pass

            records.append(self._make_record(
                name=f"{name} 구간",
                course_type="river",
                lat=s_lat,
                lon=s_lon,
                distance_m=round(dist_m or geom.length * 111_000, 0),
            ))
        return records

    def build_bike_records(self) -> list:
        """
        서울시 자전거도로 CSV에서 시작 좌표를 추출하여 courses INSERT용 dict 목록을 반환합니다.
        """
        if self.data["bike"] is None:
            return []

        df        = self.data["bike"]
        name_col  = _find_col(df, ["노선명", "구간명", "자전거도로명", "시설명"])
        dist_col  = _find_col(df, ["총길이(km)", "연장(m)", "연장", "거리(m)", "구간길이", "거리(km)", "거리"])
        s_lat_col = _find_col(df, ["기점위도", "시작위도", "출발위도", "Y좌표시작(WGS84)", "시작Y", "START_LAT"])
        s_lon_col = _find_col(df, ["기점경도", "시작경도", "출발경도", "X좌표시작(WGS84)", "시작X", "START_LNG"])

        if not all([name_col, s_lat_col, s_lon_col]):
            print(f"  ⚠️  필수 컬럼 없음 — 자전거도로 삽입 건너뜀. 컬럼: {list(df.columns)}")
            return []

        records = []
        for _, row in df.iterrows():
            name = str(row[name_col]).strip()
            if not name or name == "nan":
                continue
            try:
                s_lat = float(row[s_lat_col])
                s_lon = float(row[s_lon_col])
            except (ValueError, TypeError):
                continue
            if not (37.4 <= s_lat <= 37.7 and 126.7 <= s_lon <= 127.2):
                continue

            dist_m: Optional[float] = None
            if dist_col:
                try:
                    val = float(str(row[dist_col]).replace(",", "").strip())
                    dist_m = val * 1000 if ("km" in dist_col.lower() or val < 100) else val
                except (ValueError, TypeError):
                    pass

            records.append(self._make_record(
                name=f"{name} 자전거도로",
                course_type="bike_track",
                lat=s_lat,
                lon=s_lon,
                distance_m=round(dist_m, 0) if dist_m else None,
            ))
        return records

    def update_node(self) -> None:
        """
        courses를 초기화하고 전체 데이터의 달리기 코스 시작점을 저장합니다.
        """
        records = (
            self.build_river_records()
            + self.build_park_records()
            + self.build_trail_records()
            + self.build_river_geojson_records()
            + self.build_bike_records()
        )
        RunningRepository.save_all(records)
        print(f"  ✅ 달리기 코스 {len(records)}건 저장 완료")

    def update_edge(self) -> None:
        """
        달리기 코스 H3 기반으로 walk_edges.running_score를 업데이트합니다.
        """
        EdgeRepository.ensure_score_column("running_score")
        CollectorUtils.update_edge_scores("running_score", RunningRepository.get_running_h3_counts())

    def save(self) -> None:
        """
        courses를 저장한 후 walk_edges.running_score를 업데이트합니다.
        """
        self.update_node()
        self.update_edge()


if __name__ == "__main__":
    collector = RunningCourseCollector()
    collector.save()
