import math
from typing import Optional

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, MultiLineString

from src.data.sources.csv_source import CSVSource
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
    if distance_m is None or distance_m < 5_000:
        return "easy"
    if distance_m < 10_000:
        return "medium"
    return "hard"


def _find_col(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


# ──────────────────────────────────────────────────────────────
# Collector
# ──────────────────────────────────────────────────────────────

class RunningCourseCollector:
    def __init__(self):
        self.csv = CSVSource()
        self.RIVER_GEOJSON = "src/data/raw/서울시 하천.geojson"
        self.river_gdf = self._load_river_geojson()

    def _load_river_geojson(self) -> Optional[gpd.GeoDataFrame]:
        try:
            gdf = gpd.read_file(self.RIVER_GEOJSON)
            if gdf.crs and gdf.crs.to_epsg() != 4326:
                gdf = gdf.to_crs(epsg=4326)
            return gdf
        except Exception:
            print(f"  ⚠️  파일 없음: {self.RIVER_GEOJSON}")
            return None

    def _make_record(
        self,
        name: str,
        course_type: str,
        lat: float,
        lon: float,
        distance_m: Optional[float] = None,
        difficulty: Optional[str] = None,
        csv_raw_id: Optional[int] = None,
    ) -> dict:
        return {
            "csv_raw_id":  csv_raw_id,
            "name":        name,
            "course_type": course_type,
            "difficulty":  difficulty or _classify_difficulty(distance_m),
            "geom":        CollectorUtils.make_point(lat, lon),
        }

    def build_river_records(self) -> list:
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
        gdf = self.csv.get("type", "running_park")
        if gdf.empty:
            return []

        def _is_running_park(name: str) -> bool:
            return any(k in str(name).strip() for k in RUNNING_PARK_CONFIG)

        records = []
        for _, row in gdf.iterrows():
            park_name = str(row.get("name") or "").strip()
            if not _is_running_park(park_name):
                continue

            lat = row.geometry.y
            lon = row.geometry.x
            if not (37.4 <= lat <= 37.7 and 126.7 <= lon <= 127.2):
                continue

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
                csv_raw_id=row.get("csv_raw_id"),
            ))
        return records

    def build_trail_records(self) -> list:
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
        if self.river_gdf is None:
            return []

        gdf     = self.river_gdf
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
        gdf = self.csv.get("type", "bike_road")
        if gdf.empty:
            return []

        dist_col = "총길이(km)"

        records = []
        for _, row in gdf.iterrows():
            name = row.get("name")

            lon, lat = row.geometry.coords[0][:2]

            dist_m: Optional[float] = None
            if dist_col:
                try:
                    val = float(str(row.get(dist_col, "")).replace(",", "").strip())
                    dist_m = val * 1000 if ("km" in dist_col.lower() or val < 100) else val
                except (ValueError, TypeError):
                    pass

            records.append(self._make_record(
                name=f"{name} 자전거도로",
                course_type="bike_track",
                lat=lat,
                lon=lon,
                distance_m=round(dist_m, 0) if dist_m else None,
                csv_raw_id=row.get("csv_raw_id"),
            ))
        return records

    def update_node(self) -> None:
        records = (
            self.build_river_records()
            + self.build_park_records()
            + self.build_trail_records()
            + self.build_river_geojson_records()
            + self.build_bike_records()
        )
        RunningRepository.save_all(records)

    def update_edge(self) -> None:
        EdgeRepository.ensure_score_column("running_score")
        CollectorUtils.update_edge_scores("running_score", RunningRepository.get_running_h3_counts())

    def save(self) -> None:
        if RunningRepository.is_populated():
            print("  ⏭️  running_layer 이미 적재됨, 스킵")
            return
        self.update_node()
        self.update_edge()


if __name__ == "__main__":
    collector = RunningCourseCollector()
    collector.save()
