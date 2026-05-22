"""
런닝/다이어트 코스 데이터 수집기

서울시 열린데이터광장 데이터를 파싱하여 COURSE + COURSE_TAG 테이블에 삽입합니다.

지원 데이터 소스
-----------------
1. 서울시 주요 공원현황 XLSX  → course_type='park',  is_circular=True
   - 파일: src/data/raw/서울시 주요 공원현황.csv (또는 .xlsx)
   - 컬럼: 공원명, X좌표(WGS84), Y좌표(WGS84), 면적
   - 출처: 서울시 열린데이터광장 (2026년 기준 131개 공원)

2. 하천변 코스 정적 데이터 (선형 GeoJSON 미제공으로 직접 정의)
   - 서울시 하천 현황 CSV는 통계 데이터(좌표 없음)이므로
     실제 하천 구간 좌표는 직접 정의합니다.
   - 포함 하천: 한강(반포·여의도), 청계천, 안양천, 중랑천

실행 방법
---------
    python -m src.data.collectors.running_course_collector
"""

from __future__ import annotations

import math
from typing import Optional

import pandas as pd
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
        "start_lat": 37.5121, "start_lng": 126.9994,
        "end_lat":   37.5228, "end_lng": 126.9706,
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
        "start_lat": 37.5285, "start_lng": 126.9326,
        "end_lat":   37.5285, "end_lng": 126.9326,
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
        "start_lat": 37.5700, "start_lng": 126.9784,
        "end_lat":   37.5637, "end_lng": 127.0636,
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
        "start_lat": 37.5270, "start_lng": 126.8560,
        "end_lat":   37.5390, "end_lng": 126.8780,
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
        "start_lat": 37.6490, "start_lng": 127.0760,
        "end_lat":   37.5390, "end_lng": 127.0780,
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


def _point_wkt(lat: float, lng: float) -> str:
    return f"SRID=4326;POINT({lng} {lat})"


def _line_wkt(start_lat: float, start_lng: float, end_lat: float, end_lng: float) -> str:
    """단순 직선 LINESTRING (실제 경로 데이터가 없을 때 대체용)"""
    return f"SRID=4326;LINESTRING({start_lng} {start_lat}, {end_lng} {end_lat})"


def _classify_difficulty(distance_m: Optional[float]) -> str:
    if distance_m is None:
        return "easy"
    if distance_m < 5_000:
        return "easy"
    if distance_m < 10_000:
        return "medium"
    return "hard"


# ──────────────────────────────────────────────────────────────
# 삽입 함수
# ──────────────────────────────────────────────────────────────

def _insert_course(session: Session, course_data: dict, tags: list[str]) -> None:
    """Course + CourseTag 레코드를 세션에 추가 (commit은 호출부에서)"""
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
    """하천변 코스 정적 데이터 삽입"""
    count = 0
    for item in RIVER_COURSES:
        s_lat, s_lng = item["start_lat"], item["start_lng"]
        e_lat, e_lng = item["end_lat"],   item["end_lng"]

        course_data = {
            "name":        item["name"],
            "course_type": item["course_type"],
            "is_circular": item["is_circular"],
            "distance_m":  item.get("distance_m"),
            "difficulty":  item.get("difficulty", _classify_difficulty(item.get("distance_m"))),
            "description": item.get("description"),
            "source":      item.get("source"),
            "geom":        _line_wkt(s_lat, s_lng, e_lat, e_lng),
            "start_geom":  _point_wkt(s_lat, s_lng),
            "end_geom":    _point_wkt(e_lat, e_lng),
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
        lng = row.get("X좌표(WGS84)")
        lat = row.get("Y좌표(WGS84)")

        if pd.isna(lng) or pd.isna(lat):
            continue

        try:
            lat, lng = float(lat), float(lng)
        except (ValueError, TypeError):
            continue

        # 좌표 유효성 검사 (서울 범위)
        if not (37.4 <= lat <= 37.7 and 126.7 <= lng <= 127.2):
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
            "start_geom":  _point_wkt(lat, lng),
            "end_geom":    _point_wkt(lat, lng),  # 순환이므로 동일
        }
        _insert_course(session, course_data, config["tags"])
        count += 1

    return count


# ──────────────────────────────────────────────────────────────
# 메인 진입점
# ──────────────────────────────────────────────────────────────

def collect_running_courses(
    park_file: str = "src/data/raw/서울시 주요 공원현황.xlsx",
) -> None:
    """
    런닝 코스 전체 수집 및 DB 삽입.

    Args:
        park_file: 서울시 주요 공원현황 XLSX 또는 CSV 경로
                   기본값: src/data/raw/서울시 주요 공원현황.xlsx
    """
    print("🏃 런닝 코스 데이터 수집 시작...")

    with Session(engine) as session:
        # 1. 하천변 코스 (정적 데이터)
        #    서울시 하천 현황 CSV는 통계 데이터(좌표 없음)이므로
        #    실제 하천 구간 좌표를 직접 정의한 RIVER_COURSES 사용
        river_count = load_river_courses(session)
        print(f"  ✅ 하천변 코스 {river_count}건 삽입")

        # 2. 공원 코스 (XLSX 파싱)
        park_count = load_park_courses(session, park_file)
        print(f"  ✅ 공원 코스 {park_count}건 삽입")

        session.commit()

    total = river_count + park_count
    print(f"🎉 완료! 총 {total}건의 런닝 코스가 DB에 저장되었습니다.")


if __name__ == "__main__":
    collect_running_courses()
