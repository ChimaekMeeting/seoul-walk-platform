"""
런닝 코스 테이블 마이그레이션 스크립트

기존 init_db() 를 건드리지 않고 COURSE / COURSE_TAG 테이블만 독립적으로 생성합니다.
팀원과 합의 후 init_db() 에 통합하거나, 이 스크립트를 단독 실행해도 됩니다.

실행 방법
---------
    python -m src.data.collectors.running_course_migration
"""

from sqlalchemy import text

from src.database.postgresql import engine
from src.entity.base import Base

# Course, CourseTag 를 Base.metadata 에 등록하기 위해 반드시 임포트
from src.entity.course import Course, CourseTag  # noqa: F401


def migrate_running_tables() -> None:
    """COURSE + COURSE_TAG 테이블 생성 (이미 존재하면 건너뜀)"""
    print("🔧 런닝 코스 테이블 마이그레이션 시작...")

    with engine.begin() as conn:
        # PostGIS 확장 (이미 설치돼 있으면 무시)
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))

    # checkfirst=True → 테이블이 이미 있으면 건너뜀
    Base.metadata.create_all(
        bind=engine,
        tables=[Course.__table__, CourseTag.__table__],
        checkfirst=True,
    )

    print("  ✅ courses 테이블 생성 완료")
    print("  ✅ course_tags 테이블 생성 완료")
    print("🎉 마이그레이션 완료!")


if __name__ == "__main__":
    migrate_running_tables()

    # 테이블 생성 후 바로 데이터 삽입하려면 아래 주석 해제
    # from src.data.collectors.running_course_collector import collect_running_courses
    # collect_running_courses(
    #     park_file     = "src/data/raw/서울시 주요 공원현황.xlsx",
    #     trail_file    = "src/data/raw/서울 둘레길.csv",
    #     river_geojson = "src/data/raw/서울시 하천.geojson",
    #     bike_file     = "src/data/raw/서울시 자전거도로.csv",
    # )
