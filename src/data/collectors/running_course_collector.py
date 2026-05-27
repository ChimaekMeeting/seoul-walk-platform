"""
런닝/다이어트 코스 데이터 수집기

서울시 열린데이터광장 데이터를 파싱하여 COURSE + COURSE_TAG 테이블에 삽입합니다.

지원 데이터 소스
-----------------
1. 서울시 주요 공원현황 XLSX  → course_type='park',  is_circular=True
   - 파일: src/data/raw/서울시 주요 공원현황.xlsx (또는 .csv)
   - 컬럼: 공원명, X좌표(WGS84), Y좌표(WGS84), 면적
   - 출처: 서울시 열린데이터광장

2. 하천변 코스 정적 데이터 (선형 GeoJSON 미제공으로 직접 정의)
   - 한강(반포·여의도), 청계천, 안양천, 중랑천 → course_type='river'

3. 서울 둘레길 CSV  → course_type='trail', is_circular=False (구간별)
   - 파일: src/data/raw/서울 둘레길.csv
   - 예상 컬럼: 구간명/코스명, 거리(km), 출발지위도, 출발지경도, 도착지위도, 도착지경도

4. 서울시 하천 GeoJSON  → course_type='river', is_circular=False
   - 파일: src/data/raw/서울시 하천.geojson
   - 예상 속성: 하천명/RIVER_NM, SHAPE_LEN/길이
   - 예상 지오메트리: LINESTRING 또는 MULTILINESTRING (SRID=4326 또는 EPSG:5179)

5. 서울시 자전거도로 CSV  → course_type='bike_track', is_circular=False
   - 파일: src/data/raw/서울시 자전거도로.csv
   - 예상 컬럼: 노선명/구간명, 연장(m)/거리(km), 시작위도, 시작경도, 종료위도, 종료경도

실행 방법
---------
    python -m src.data.collectors.running_course_collector
"""

from __future__ import annotations

import math
from typing import Optional

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, MultiLineString
from sqlalchemy.orm import Session

from src.database.postgresql import engine
from src.entity.course import Course, CourseTag


# ──────────────────────────────────────────────────────────────
# 하천변 코스 정적 데이터
# (서울시 열린데이터광장에 선형 GeoJSON이 없는 경우 직접 정의)
# ──────────────────────────────────────────────────────────────

RIVER_COURSES: list[dict] = [
    {
        "name": "한강 반포 구간",
        "course_type": "river",
        "is_circular": False,
        "distance_m": 6_400,
        "difficulty": "easy",
        "description": "반포한강공원 ~ 이촌한강공원 편도 구간. 평탄하고 신호등 없음.",
        "source": "서울시 열린데이터광장",
        "start_lat": 37.5121, "start_lon": 126.9994,
        "end_lat":   37.5228, "end_lon": 126.9706,
        "tags": ["런닝", "다이어트", "하천변", "야간가능"],
    },
    {
        "name": "한강 여의도 순환 코스",
        "course_type": "river",
        "is_circular": True,
        "distance_m": 7_000,
        "difficulty": "easy",
        "description": "여의도한강공원 순환 루프. 자전거도로 겸용 트랙 포함.",
        "source": "서울시 열린데이터광장",
        "start_lat": 37.5285, "start_lon": 126.9326,
        "end_lat":   37.5285, "end_lon": 126.9326,
        "tags": ["런닝", "다이어트", "하천변", "자전거도로", "야간가능"],
    },
    {
        "name": "청계천 전 구간",
        "course_type": "river",
        "is_circular": False,
        "distance_m": 10_920,
        "difficulty": "easy",
        "description": "청계광장 ~ 고산자교 편도. 도심 속 평탄 하천변 코스.",
        "source": "서울시 열린데이터광장",
        "start_lat": 37.5700, "start_lon": 126.9784,
        "end_lat":   37.5637, "end_lon": 127.0636,
        "tags": ["런닝", "다이어트", "하천변"],
    },
    {
        "name": "안양천 서울 구간",
        "course_type": "river",
        "is_circular": False,
        "distance_m": 12_000,
        "difficulty": "easy",
        "description": "안양천 서울 구간 편도. 한강 합류 지점까지 평탄 직선 코스.",
        "source": "서울시 열린데이터광장",
        "start_lat": 37.5270, "start_lon": 126.8560,
        "end_lat":   37.5390, "end_lon": 126.8780,
        "tags": ["런닝", "다이어트", "하천변"],
    },
    {
        "name": "중랑천 전 구간",
        "course_type": "river",
        "is_circular": False,
        "distance_m": 15_000,
        "difficulty": "medium",
        "description": "중랑천 서울 구간 편도. 자전거도로 겸용 트랙 포함.",
        "source": "서울시 열린데이터광장",
        "start_lat": 37.6490, "start_lon": 127.0760,
        "end_lat":   37.5390, "end_lon": 127.0780,
        "tags": ["런닝", "다이어트", "하천변", "자전거도로"],
    },
]

# ──────────────────────────────────────────────────────────────
# 런닝 적합 공원 목록
# 서울시 주요 공원현황 XLSX 실제 데이터 기반으로 확인된 공원명
# (XLSX 공원명 컬럼과 정확히 일치해야 필터링됨)
# ──────────────────────────────────────────────────────────────

# 공원명 → 추가 태그 매핑
# XLSX에 실제 존재하는 공원명만 포함 (2026년 기준 확인)
RUNNING_PARK_CONFIG: dict[str, dict] = {
    # 대형 순환 트랙 보유 공원 (런닝 최적)
    "올림픽공원":       {"tags": ["런닝", "다이어트", "공원", "자전거도로", "야간가능"], "difficulty_override": "easy"},
    "보라매공원":       {"tags": ["런닝", "다이어트", "공원", "야간가능"],              "difficulty_override": "easy"},
    "서울숲":           {"tags": ["런닝", "다이어트", "공원", "하천변", "야간가능"],    "difficulty_override": "easy"},
    "월드컵공원":       {"tags": ["런닝", "다이어트", "공원", "야간가능"],              "difficulty_override": "medium"},
    "북서울꿈의숲":     {"tags": ["런닝", "다이어트", "공원"],                          "difficulty_override": None},
    # 중형 공원
    "남산공원":         {"tags": ["런닝", "다이어트", "공원"],                          "difficulty_override": "medium"},
    "용산가족공원":     {"tags": ["런닝", "다이어트", "공원", "야간가능"],              "difficulty_override": "easy"},
    "어린이대공원":     {"tags": ["런닝", "다이어트", "공원"],                          "difficulty_override": "easy"},
    "천호근린공원":     {"tags": ["런닝", "다이어트", "공원"],                          "difficulty_override": "easy"},
    "여의도근린공원":   {"tags": ["런닝", "다이어트", "공원", "자전거도로", "야간가능"], "difficulty_override": "easy"},
    "송파나루근린공원(석촌호수)": {"tags": ["런닝", "다이어트", "공원", "야간가능"],   "difficulty_override": "easy"},
    "선유도근린공원":   {"tags": ["런닝", "다이어트", "공원", "하천변"],               "difficulty_override": "easy"},
    "노량진공원":       {"tags": ["런닝", "다이어트", "공원"],                          "difficulty_override": "easy"},
    "손기정체육공원":   {"tags": ["런닝", "다이어트", "공원"],                          "difficulty_override": "easy"},
    "서서울호수공원":   {"tags": ["런닝", "다이어트", "공원"],                          "difficulty_override": "easy"},
}

# 필터링용 공원명 목록 (부분 일치 허용)
RUNNING_PARK_NAMES: list[str] = list(RUNNING_PARK_CONFIG.keys())


# ──────────────────────────────────────────────────────────────
# 헬퍼 함수
# ──────────────────────────────────────────────────────────────

def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """두 좌표 간 거리(미터) 계산 — Haversine 공식"""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _point_wkt(lat: float, lon: float) -> str:
    """위경도 → ``SRID=4326;POINT(lon lat)`` WKT 문자열 반환."""
    return f"SRID=4326;POINT({lon} {lat})"


def _line_wkt(start_lat: float, start_lng: float, end_lat: float, end_lng: float) -> str:
    """두 좌표를 잇는 직선 ``SRID=4326;LINESTRING`` WKT 반환. 실제 경로 데이터가 없을 때 대체용."""
    return f"SRID=4326;LINESTRING({start_lng} {start_lat}, {end_lng} {end_lat})"


def _classify_difficulty(distance_m: Optional[float]) -> str:
    """
    거리(미터) 기반 난이도 분류.

    Returns:
        str: ``"easy"`` (< 5km) | ``"medium"`` (5–10km) | ``"hard"`` (≥ 10km).
             ``distance_m``이 ``None``이면 ``"easy"`` 반환.
    """
    if distance_m is None:
        return "easy"
    if distance_m < 5_000:
        return "easy"
    if distance_m < 10_000:
        return "medium"
    return "hard"


def _find_col(df: "pd.DataFrame", candidates: list[str]) -> Optional[str]:
    """DataFrame 컬럼 중 candidates 순서대로 첫 번째로 존재하는 컬럼명 반환"""
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _shapely_to_linestring_wkt(geom) -> Optional[str]:
    """
    Shapely LineString / MultiLineString → ``SRID=4326;LINESTRING(...)`` WKT 변환.

    MultiLineString은 가장 긴 하위 지오메트리를 사용합니다.

    Returns:
        str | None: WKT 문자열. 변환 불가하거나 빈 지오메트리면 ``None``.
    """
    if isinstance(geom, MultiLineString):
        geom = max(geom.geoms, key=lambda g: g.length)
    if not isinstance(geom, LineString) or geom.is_empty:
        return None
    pts = ", ".join(f"{x} {y}" for x, y in geom.coords)
    return f"SRID=4326;LINESTRING({pts})"


# ──────────────────────────────────────────────────────────────
# 삽입 함수
# ──────────────────────────────────────────────────────────────

def _insert_course(session: Session, course_data: dict, tags: list[str]) -> None:
    """
    ``Course`` + ``CourseTag`` 레코드를 세션에 추가합니다. commit은 호출부에서 수행합니다.

    Args:
        session     (Session)   : SQLAlchemy 세션.
        course_data (dict)      : Course 모델에 대응하는 필드 딕셔너리.
                                  필수 키: ``name``, ``course_type``, ``is_circular``.
                                  선택 키: ``distance_m``, ``difficulty``, ``description``,
                                  ``source``, ``geom``, ``start_geom``, ``end_geom``.
        tags        (list[str]) : 연결할 태그 문자열 목록.
    """
    course = Course(
        name=course_data["name"],
        course_type=course_data["course_type"],
        is_circular=course_data["is_circular"],
        distance_m=course_data.get("distance_m"),
        difficulty=course_data.get("difficulty"),
        description=course_data.get("description"),
        source=course_data.get("source"),
        geom=course_data.get("geom"),
        start_geom=course_data.get("start_geom"),
        end_geom=course_data.get("end_geom"),
    )
    session.add(course)
    session.flush()  # course.id 확보

    for tag in tags:
        session.add(CourseTag(course_id=course.id, tag=tag))


def load_river_courses(session: Session) -> int:
    """
    ``RIVER_COURSES`` 정적 데이터를 DB에 삽입합니다.

    Args:
        session (Session): SQLAlchemy 세션.

    Returns:
        int: 삽입된 코스 건수.
    """
    count = 0
    for item in RIVER_COURSES:
        s_lat, s_lon = item["start_lat"], item["start_lon"]
        e_lat, e_lon = item["end_lat"],   item["end_lon"]

        course_data = {
            "name":        item["name"],
            "course_type": item["course_type"],
            "is_circular": item["is_circular"],
            "distance_m":  item.get("distance_m"),
            "difficulty":  item.get("difficulty", _classify_difficulty(item.get("distance_m"))),
            "description": item.get("description"),
            "source":      item.get("source"),
            "geom":        _line_wkt(s_lat, s_lon, e_lat, e_lon),
            "start_geom":  _point_wkt(s_lat, s_lon),
            "end_geom":    _point_wkt(e_lat, e_lon),
        }
        _insert_course(session, course_data, item["tags"])
        count += 1

    return count


def load_park_courses(session: Session, xlsx_path: str) -> int:
    """
    서울시 주요 공원현황 XLSX에서 런닝 적합 공원을 파싱하여 삽입.

    XLSX 컬럼 (실제 데이터 기준):
        연번, 관리부서, 전화번호, 공원명, 공원개요, 면적,
        개원일, 주요시설, 주요식물, 안내도, 오시는길,
        이용시참고사항, 이미지, 지역, 공원주소,
        X좌표(GRS80TM), Y좌표(GRS80TM),
        X좌표(WGS84), Y좌표(WGS84), 바로가기

    Args:
        session  : SQLAlchemy 세션
        xlsx_path: XLSX 또는 CSV 파일 경로
    """
    # xlsx / csv 모두 지원
    try:
        if xlsx_path.endswith(".xlsx"):
            df = pd.read_excel(xlsx_path, header=1)   # 2번째 행이 실제 컬럼명
        else:
            df = pd.read_csv(xlsx_path, encoding="cp949")
    except FileNotFoundError:
        print(f"  ⚠️  파일 없음: {xlsx_path} — 공원 코스 삽입 건너뜀")
        return 0

    # 컬럼명 공백 제거
    df.columns = [str(c).strip() for c in df.columns]

    # 런닝 적합 공원 필터링 (부분 일치)
    def _is_running_park(name: str) -> bool:
        name = str(name).strip()
        return any(target in name for target in RUNNING_PARK_NAMES)

    mask = df["공원명"].apply(_is_running_park)
    df_running = df[mask].copy()

    count = 0
    for _, row in df_running.iterrows():
        # WGS84 좌표 사용 (X=경도, Y=위도)
        lon = row.get("X좌표(WGS84)")
        lat = row.get("Y좌표(WGS84)")

        if pd.isna(lon) or pd.isna(lat):
            continue

        try:
            lat, lon = float(lat), float(lon)
        except (ValueError, TypeError):
            continue

        # 좌표 유효성 검사 (서울 범위)
        if not (37.4 <= lat <= 37.7 and 126.7 <= lon <= 127.2):
            continue

        park_name = str(row["공원명"]).strip()

        # 공원 면적 파싱 (예: "1,513,491.2㎡" → 1513491.2)
        area_raw = str(row.get("면적", "")).strip()
        area_m2: Optional[float] = None
        for token in area_raw.replace(",", "").split():
            try:
                val = float(token.replace("㎡", "").replace("m²", ""))
                if val > 0:
                    area_m2 = val
                    break
            except ValueError:
                continue

        # 둘레 추정: 정사각형 근사 (둘레 ≈ 4√면적)
        estimated_distance_m: Optional[float] = None
        if area_m2:
            estimated_distance_m = round(4 * math.sqrt(area_m2), 0)

        # 공원별 설정 조회 (정확 일치 우선, 없으면 부분 일치)
        config = RUNNING_PARK_CONFIG.get(park_name)
        if config is None:
            for key, val in RUNNING_PARK_CONFIG.items():
                if key in park_name:
                    config = val
                    break
        if config is None:
            config = {"tags": ["런닝", "다이어트", "공원"], "difficulty_override": None}

        difficulty = config["difficulty_override"] or _classify_difficulty(estimated_distance_m)

        course_data = {
            "name":        f"{park_name} 순환 코스",
            "course_type": "park",
            "is_circular": True,
            "distance_m":  estimated_distance_m,
            "difficulty":  difficulty,
            "description": f"{park_name} 내부 순환 런닝 코스.",
            "source":      "서울시 열린데이터광장 — 서울시 주요 공원현황",
            "geom":        None,
            "start_geom":  _point_wkt(lat, lon),
            "end_geom":    _point_wkt(lat, lon),  # 순환이므로 동일
        }
        _insert_course(session, course_data, config["tags"])
        count += 1

    return count


def load_trail_courses(session: Session, csv_path: str) -> int:
    """
    서울 둘레길 코스 CSV 파싱 및 삽입.

    예상 컬럼 (서울시 열린데이터광장 기준):
        구간명 / 코스명, 거리(km), 출발지위도, 출발지경도, 도착지위도, 도착지경도

    course_type='trail', 태그=['런닝','다이어트','둘레길']
    """
    try:
        df = pd.read_csv(csv_path, encoding="cp949")
    except UnicodeDecodeError:
        df = pd.read_csv(csv_path, encoding="utf-8")
    except FileNotFoundError:
        print(f"  ⚠️  파일 없음: {csv_path} — 둘레길 코스 삽입 건너뜀")
        return 0

    df.columns = [str(c).strip() for c in df.columns]

    # 서울 둘레길 코스정보 컬럼 포함
    name_col  = _find_col(df, ["둘레길 명", "구간명", "코스명", "코스_구간명", "코스구분"])
    dist_col  = _find_col(df, ["둘레길 길이 (km)", "거리(km)", "구간거리", "총거리", "거리"])
    diff_col  = _find_col(df, ["난이도[한글]", "난이도", "difficulty"])
    desc_col  = _find_col(df, ["둘레길 설명", "코스설명", "설명"])
    s_lat_col = _find_col(df, ["출발지위도", "출발위도", "시작위도", "START_LAT"])
    s_lon_col = _find_col(df, ["출발지경도", "출발경도", "시작경도", "START_LNG"])
    e_lat_col = _find_col(df, ["도착지위도", "도착위도", "종료위도", "END_LAT"])
    e_lon_col = _find_col(df, ["도착지경도", "도착경도", "종료경도", "END_LNG"])

    if not name_col:
        print(
            f"  ⚠️  이름 컬럼 없음 — 둘레길 삽입 건너뜀. 실제 컬럼: {list(df.columns)}"
        )
        return 0

    # 난이도 한글 → 영문 변환
    _diff_map = {"상급": "hard", "중급": "medium", "하급": "easy", "초급": "easy"}

    no_coord = not (s_lat_col and s_lon_col)
    if no_coord:
        print("  ℹ️  좌표 컬럼 없음 — 둘레길 코스를 좌표 NULL로 삽입합니다.")

    count = 0
    for _, row in df.iterrows():
        name = str(row[name_col]).strip()
        if not name or name == "nan":
            continue

        dist_m: Optional[float] = None
        if dist_col:
            try:
                val = float(str(row[dist_col]).replace(",", "").replace("km", "").strip())
                dist_m = val * 1000
            except (ValueError, TypeError):
                pass

        diff_raw = str(row[diff_col]).strip() if diff_col else ""
        difficulty = _diff_map.get(diff_raw) or _classify_difficulty(dist_m)

        desc = str(row[desc_col]).strip() if desc_col else f"{name} 둘레길 코스."
        if desc == "nan":
            desc = f"{name} 둘레길 코스."

        if no_coord:
            course_data = {
                "name":        f"{name} 둘레길",
                "course_type": "trail",
                "is_circular": False,
                "distance_m":  round(dist_m, 0) if dist_m else None,
                "difficulty":  difficulty,
                "description": desc,
                "source":      "서울시 열린데이터광장 — 서울 둘레길",
                "geom":        None,
                "start_geom":  None,
                "end_geom":    None,
            }
        else:
            try:
                s_lat = float(row[s_lat_col])
                s_lon = float(row[s_lon_col])
            except (ValueError, TypeError):
                continue
            if not (37.4 <= s_lat <= 37.7 and 126.7 <= s_lon <= 127.2):
                continue
            try:
                e_lat = float(row[e_lat_col]) if e_lat_col else s_lat
                e_lon = float(row[e_lon_col]) if e_lon_col else s_lon
            except (ValueError, TypeError):
                e_lat, e_lon = s_lat, s_lon
            if dist_m is None:
                dist_m = _haversine_m(s_lat, s_lon, e_lat, e_lon)
            is_circular = _haversine_m(s_lat, s_lon, e_lat, e_lon) < 200
            course_data = {
                "name":        f"{name} 둘레길",
                "course_type": "trail",
                "is_circular": is_circular,
                "distance_m":  round(dist_m, 0) if dist_m else None,
                "difficulty":  difficulty,
                "description": desc,
                "source":      "서울시 열린데이터광장 — 서울 둘레길",
                "geom":        _line_wkt(s_lat, s_lon, e_lat, e_lon),
                "start_geom":  _point_wkt(s_lat, s_lon),
                "end_geom":    _point_wkt(e_lat, e_lon),
            }

        _insert_course(session, course_data, ["런닝", "다이어트", "둘레길"])
        count += 1

    return count


def load_river_geojson_courses(session: Session, geojson_path: str) -> int:
    """
    서울시 하천 GeoJSON 파싱 및 삽입.

    예상 속성 (서울시 열린데이터광장 기준):
        하천명 / RIVER_NM / WATERBODY_NM,  SHAPE_LEN / 길이 / 연장
    예상 지오메트리: LINESTRING 또는 MULTILINESTRING
    CRS: EPSG:4326 또는 EPSG:5179 (자동 변환)

    course_type='river', 태그=['런닝','다이어트','하천변']
    """
    try:
        gdf = gpd.read_file(geojson_path)
    except FileNotFoundError:
        print(f"  ⚠️  파일 없음: {geojson_path} — 하천 GeoJSON 코스 삽입 건너뜀")
        return 0
    except Exception as exc:
        print(f"  ⚠️  GeoJSON 읽기 실패: {exc} — 하천 GeoJSON 코스 삽입 건너뜀")
        return 0

    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    name_col = _find_col(gdf, ["하천명", "RIVER_NM", "WATERBODY_NM", "HCH_NAME", "name:ko", "name", "NAME"])
    len_col  = _find_col(gdf, ["SHAPE_LEN", "길이", "연장", "구간거리", "LENGTH"])

    count = 0
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue

        wkt = _shapely_to_linestring_wkt(geom)
        if wkt is None:
            continue

        name = str(row[name_col]).strip() if name_col else "하천"
        if not name or name == "nan":
            name = "하천"

        dist_m: Optional[float] = None
        if len_col:
            try:
                val = float(row[len_col])
                # SHAPE_LEN이 degree 단위(< 1)면 미터로 근사 변환
                dist_m = val if val >= 1.0 else val * 111_000
            except (ValueError, TypeError):
                pass
        if dist_m is None:
            dist_m = geom.length * 111_000  # degree → 미터 근사

        # 시작·끝 좌표 (lon, lat 순서)
        base_geom = (
            max(geom.geoms, key=lambda g: g.length)
            if isinstance(geom, MultiLineString)
            else geom
        )
        s_lon, s_lat = base_geom.coords[0][:2]
        e_lon, e_lat = base_geom.coords[-1][:2]

        if not (37.4 <= s_lat <= 37.7 and 126.7 <= s_lon <= 127.2):
            continue

        course_data = {
            "name":        f"{name} 구간",
            "course_type": "river",
            "is_circular": False,
            "distance_m":  round(dist_m, 0),
            "difficulty":  _classify_difficulty(dist_m),
            "description": f"{name} 하천변 런닝 코스.",
            "source":      "서울시 열린데이터광장 — 서울시 하천",
            "geom":        wkt,
            "start_geom":  _point_wkt(s_lat, s_lon),
            "end_geom":    _point_wkt(e_lat, e_lon),
        }
        _insert_course(session, course_data, ["런닝", "다이어트", "하천변"])
        count += 1

    return count


def load_bike_courses(session: Session, csv_path: str) -> int:
    """
    서울시 자전거도로 CSV 파싱 및 삽입.

    예상 컬럼 (서울시 열린데이터광장 기준):
        노선명 / 구간명,  연장(m) / 거리(km),
        시작위도, 시작경도, 종료위도, 종료경도

    course_type='bike_track', 태그=['런닝','다이어트','자전거도로']
    """
    try:
        df = pd.read_csv(csv_path, encoding="cp949")
    except UnicodeDecodeError:
        df = pd.read_csv(csv_path, encoding="utf-8")
    except FileNotFoundError:
        print(f"  ⚠️  파일 없음: {csv_path} — 자전거도로 코스 삽입 건너뜀")
        return 0

    df.columns = [str(c).strip() for c in df.columns]

    name_col  = _find_col(df, ["노선명", "구간명", "자전거도로명", "시설명"])
    dist_col  = _find_col(df, ["총길이(km)", "연장(m)", "연장", "거리(m)", "구간길이", "거리(km)", "거리"])
    s_lat_col = _find_col(df, ["기점위도", "시작위도", "출발위도", "Y좌표시작(WGS84)", "시작Y", "START_LAT"])
    s_lon_col = _find_col(df, ["기점경도", "시작경도", "출발경도", "X좌표시작(WGS84)", "시작X", "START_LNG"])
    e_lat_col = _find_col(df, ["종점위도", "종료위도", "도착위도", "Y좌표끝(WGS84)", "끝Y", "END_LAT"])
    e_lon_col = _find_col(df, ["종점경도", "종료경도", "도착경도", "X좌표끝(WGS84)", "끝X", "END_LNG"])

    if not all([name_col, s_lat_col, s_lon_col]):
        print(
            f"  ⚠️  필수 컬럼(이름·출발좌표) 없음 — 자전거도로 삽입 건너뜀. "
            f"실제 컬럼: {list(df.columns)}"
        )
        return 0

    count = 0
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

        try:
            e_lat = float(row[e_lat_col]) if e_lat_col else s_lat
            e_lon = float(row[e_lon_col]) if e_lon_col else s_lon
        except (ValueError, TypeError):
            e_lat, e_lon = s_lat, s_lon

        dist_m: Optional[float] = None
        if dist_col:
            try:
                val = float(str(row[dist_col]).replace(",", "").strip())
                # 컬럼명에 'km' 포함 또는 값이 100 미만이면 km 단위로 간주
                if "km" in dist_col.lower() or val < 100:
                    dist_m = val * 1000
                else:
                    dist_m = val
            except (ValueError, TypeError):
                pass
        if dist_m is None:
            dist_m = _haversine_m(s_lat, s_lon, e_lat, e_lon)

        course_data = {
            "name":        f"{name} 자전거도로",
            "course_type": "bike_track",
            "is_circular": False,
            "distance_m":  round(dist_m, 0) if dist_m else None,
            "difficulty":  _classify_difficulty(dist_m),
            "description": f"{name} 구간 자전거도로 런닝 코스.",
            "source":      "서울시 열린데이터광장 — 서울시 자전거도로",
            "geom":        _line_wkt(s_lat, s_lon, e_lat, e_lon),
            "start_geom":  _point_wkt(s_lat, s_lon),
            "end_geom":    _point_wkt(e_lat, e_lon),
        }
        _insert_course(session, course_data, ["런닝", "다이어트", "자전거도로"])
        count += 1

    return count


# ──────────────────────────────────────────────────────────────
# 둘레길 좌표 보정 (CSV에 좌표 없는 경우 사용)
# ──────────────────────────────────────────────────────────────

# 서울 둘레길 21개 구간 출발·도착 좌표 (WGS84)
# 키: 둘레길 명 (CSV '둘레길 명' 컬럼과 일치하는 부분 문자열)
# 값: ((시작위도, 시작경도), (종료위도, 종료경도))
_TRAIL_COORDS: dict[str, tuple[tuple[float, float], tuple[float, float]]] = {
    "수락산":     ((37.6895, 127.0465), (37.6541, 127.0722)),
    "덕릉고개":   ((37.6541, 127.0722), (37.6620, 127.0800)),
    "불암산":     ((37.6620, 127.0800), (37.6218, 127.0964)),
    "용마산":     ((37.6218, 127.0964), (37.5830, 127.0958)),  # 망우·용마산
    "아차산":     ((37.5830, 127.0958), (37.5491, 127.1020)),
    "고덕산":     ((37.5491, 127.1020), (37.5475, 127.1421)),
    "일자산":     ((37.5475, 127.1421), (37.5019, 127.1248)),
    "탄천":       ((37.5019, 127.1248), (37.4849, 127.1004)),  # 장지·탄천
    "구룡산":     ((37.4849, 127.1004), (37.4705, 127.0421)),  # 대모·구룡산
    "우면산":     ((37.4705, 127.0421), (37.4773, 126.9818)),
    "관악산":     ((37.4773, 126.9818), (37.4724, 126.9637)),
    "호암산":     ((37.4724, 126.9637), (37.4630, 126.9020)),
    "안양천 상류": ((37.4630, 126.9020), (37.5032, 126.8685)),
    "안양천 하류": ((37.5032, 126.8685), (37.5619, 126.8652)),
    "하늘공원":   ((37.5616, 126.8640), (37.5961, 126.8890)),  # 노을·하늘공원
    "앵봉산":     ((37.5961, 126.8890), (37.6268, 126.9188)),  # 봉산·앵봉산
    "북한산 은평": ((37.6268, 126.9188), (37.6465, 126.9555)),
    "북한산 종로": ((37.6465, 126.9555), (37.6371, 126.9706)),
    "북한산 성북": ((37.6371, 126.9706), (37.6397, 127.0108)),
    "북한산 강북": ((37.6397, 127.0108), (37.6616, 127.0155)),
    "북한산 도봉": ((37.6616, 127.0155), (37.6895, 127.0465)),
}


def update_trail_coords(session: Session) -> int:
    """
    DB의 ``trail`` 코스 중 ``start_geom``이 NULL인 행에 ``_TRAIL_COORDS`` 좌표를 채웁니다.

    ``collect_running_courses()`` 실행 후 둘레길 CSV에 좌표가 없었던 경우를 보정합니다.

    Args:
        session (Session): SQLAlchemy 세션.

    Returns:
        int: 업데이트된 행 수.
    """
    from sqlalchemy import text as _text

    rows = session.execute(
        _text("SELECT id, name FROM courses WHERE course_type = 'trail' AND start_geom IS NULL")
    ).fetchall()

    if not rows:
        return 0

    updated = 0
    for row in rows:
        course_id, name = row.id, row.name

        coords = None
        for key, val in _TRAIL_COORDS.items():
            if key in name:
                coords = val
                break

        if coords is None:
            continue

        (s_lat, s_lon), (e_lat, e_lon) = coords
        dist_m = round(_haversine_m(s_lat, s_lon, e_lat, e_lon), 0)

        session.execute(
            _text("""
                UPDATE courses SET
                    geom       = ST_GeomFromText(:geom,       4326),
                    start_geom = ST_GeomFromText(:start_geom, 4326),
                    end_geom   = ST_GeomFromText(:end_geom,   4326),
                    distance_m = COALESCE(distance_m, :dist_m)
                WHERE id = :id
            """),
            {
                "geom":       f"LINESTRING({s_lon} {s_lat}, {e_lon} {e_lat})",
                "start_geom": f"POINT({s_lon} {s_lat})",
                "end_geom":   f"POINT({e_lon} {e_lat})",
                "dist_m":     dist_m,
                "id":         course_id,
            },
        )
        updated += 1

    return updated


# ──────────────────────────────────────────────────────────────
# 메인 진입점
# ──────────────────────────────────────────────────────────────

def collect_running_courses(
    park_file:     str = "src/data/raw/서울시 주요 공원현황.xlsx",
    trail_file:    str = "src/data/raw/서울 둘레길.csv",
    river_geojson: str = "src/data/raw/서울시 하천.geojson",
    bike_file:     str = "src/data/raw/서울시 자전거도로.csv",
) -> None:
    """
    런닝 코스 전체 수집 및 DB 삽입.

    Args:
        park_file     : 서울시 주요 공원현황 XLSX 또는 CSV
        trail_file    : 서울 둘레길 코스정보 CSV
        river_geojson : 서울시 하천 공간정보 GeoJSON
        bike_file     : 서울시 자전거도로 CSV
    """
    print("🏃 런닝 코스 데이터 수집 시작...")

    with Session(engine) as session:
        # 1. 하천변 코스 (정적 데이터 — 주요 하천 5개)
        river_count = load_river_courses(session)
        print(f"  ✅ 하천변 코스(정적) {river_count}건 삽입")

        # 2. 공원 코스 (XLSX 파싱)
        park_count = load_park_courses(session, park_file)
        print(f"  ✅ 공원 코스 {park_count}건 삽입")

        # 3. 둘레길 코스 (CSV 파싱)
        trail_count = load_trail_courses(session, trail_file)
        print(f"  ✅ 둘레길 코스 {trail_count}건 삽입")

        # 4. 하천 GeoJSON 코스 (실제 선형 지오메트리)
        river_geojson_count = load_river_geojson_courses(session, river_geojson)
        print(f"  ✅ 하천 GeoJSON 코스 {river_geojson_count}건 삽입")

        # 5. 자전거도로 코스 (CSV 파싱)
        bike_count = load_bike_courses(session, bike_file)
        print(f"  ✅ 자전거도로 코스 {bike_count}건 삽입")

        session.commit()

    total = river_count + park_count + trail_count + river_geojson_count + bike_count
    print(f"🎉 완료! 총 {total}건의 런닝 코스가 DB에 저장되었습니다.")


if __name__ == "__main__":
    collect_running_courses()
