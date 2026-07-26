"""
user_preferences 테이블에 selected_tags(JSON) 컬럼을 추가하는 일회성 마이그레이션 스크립트.

배경:
    온보딩 설문에서 유저가 선택한 원본 태그 배열을 마이페이지 등에서 하이라이트 표시하기 위해
    계산된 weights 외에 selected_tags를 별도로 보존해야 함.

실행:
    미리보기(기본): poetry run python scripts/migrate_add_selected_tags.py
    실제 적용     : poetry run python scripts/migrate_add_selected_tags.py --apply

주의:
    멱등하게 작성되어 있음 (컬럼이 이미 존재하면 건너뜀).
    그래도 운영 DB에 적용 전 반드시 백업을 권장함.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(encoding="utf-8")

from sqlalchemy import create_engine, text

DB_URL = (
    f"postgresql+psycopg2://"
    f"{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
    f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT')}"
    f"/{os.getenv('POSTGRES_DB')}?client_encoding=utf8"
)

engine = create_engine(DB_URL)

CHECK_SQL = text("""
    SELECT column_name
    FROM information_schema.columns
    WHERE table_name = 'user_preferences'
      AND column_name = 'selected_tags'
""")

ALTER_SQL = text("""
    ALTER TABLE user_preferences
    ADD COLUMN selected_tags JSON NULL
""")


def main(apply: bool) -> None:
    with engine.connect() as conn:
        result = conn.execute(CHECK_SQL).fetchone()
        if result is not None:
            print("✅ selected_tags 컬럼이 이미 존재합니다. 건너뜁니다.")
            return

        if apply:
            conn.execute(ALTER_SQL)
            conn.commit()
            print("✅ 적용 완료: user_preferences.selected_tags(JSON NULL) 컬럼 추가됨")
        else:
            print("[DRY-RUN] 실행 예정 SQL:")
            print("  ALTER TABLE user_preferences ADD COLUMN selected_tags JSON NULL;")
            print("\n실제로 반영하려면 --apply 를 붙여 다시 실행하세요.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="user_preferences.selected_tags 컬럼 추가 마이그레이션")
    parser.add_argument("--apply", action="store_true", help="실제로 DB에 반영 (미지정 시 dry-run)")
    main(parser.parse_args().apply)
