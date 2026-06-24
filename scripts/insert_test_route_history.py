"""
테스트용 유저 및 경로 기록을 DB에 삽입하는 스크립트입니다.
실행: poetry run python scripts/insert_test_route_history.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(encoding="utf-8")

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone, timedelta

from src.entity.chat_session import ChatSession  # noqa: F401
from src.entity.user_preference import UserPreference  # noqa: F401
from src.entity.banner import Banner  # noqa: F401
from src.entity.user import User, Provider
from src.entity.route_history import RouteHistory

DB_URL = (
    f"postgresql+psycopg2://"
    f"{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
    f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT')}"
    f"/{os.getenv('POSTGRES_DB')}?client_encoding=utf8"
)

engine = create_engine(DB_URL)
Session = sessionmaker(bind=engine)

def main():
    with Session() as db:
        # 이미 테스트 유저가 있으면 재사용
        existing = db.execute(
            text("SELECT id FROM users WHERE provider_id = 'test_user_001'")
        ).fetchone()

        if existing:
            user_id = existing[0]
            print(f"기존 테스트 유저 재사용 (id={user_id})")
        else:
            user = User(
                provider=Provider.KAKAO,
                provider_id="test_user_001",
                nickname="테스트유저",
            )
            db.add(user)
            db.flush()
            user_id = user.id
            print(f"테스트 유저 생성 완료 (id={user_id})")

        # 기존 기록 삭제 후 재삽입
        db.execute(text(f"DELETE FROM route_histories WHERE user_id = {user_id}"))

        histories = [
            RouteHistory(
                user_id=user_id, mode="circular_random",
                origin_lat=37.5665, origin_lon=126.9780,
                coordinates=[[37.5665,126.9780],[37.5680,126.9795],[37.5700,126.9810],[37.5665,126.9780]],
                total_km=3.2,
                created_at=datetime.now(timezone.utc) - timedelta(days=1),
            ),
            RouteHistory(
                user_id=user_id, mode="oneway_shortest",
                origin_lat=37.5512, origin_lon=126.9882,
                destination_lat=37.5600, destination_lon=126.9950,
                coordinates=[[37.5512,126.9882],[37.5550,126.9910],[37.5600,126.9950]],
                total_km=2.1,
                created_at=datetime.now(timezone.utc) - timedelta(days=3),
            ),
            RouteHistory(
                user_id=user_id, mode="circular_running",
                origin_lat=37.5796, origin_lon=126.9770,
                coordinates=[[37.5796,126.9770],[37.5810,126.9800],[37.5830,126.9780],[37.5796,126.9770]],
                total_km=5.5,
                created_at=datetime.now(timezone.utc) - timedelta(days=7),
            ),
            RouteHistory(
                user_id=user_id, mode="circular_child",
                origin_lat=37.5172, origin_lon=127.0473,
                coordinates=[[37.5172,127.0473],[37.5185,127.0490],[37.5200,127.0470],[37.5172,127.0473]],
                total_km=1.8,
                created_at=datetime.now(timezone.utc) - timedelta(days=10),
            ),
            RouteHistory(
                user_id=user_id, mode="oneway_random",
                origin_lat=37.5400, origin_lon=126.9500,
                destination_lat=37.5480, destination_lon=126.9600,
                coordinates=[[37.5400,126.9500],[37.5430,126.9540],[37.5480,126.9600]],
                total_km=4.0,
                created_at=datetime.now(timezone.utc) - timedelta(days=15),
            ),
        ]

        for h in histories:
            db.add(h)

        db.commit()
        print(f"경로 기록 {len(histories)}개 삽입 완료")
        print(f"\n테스트 계정 정보:")
        print(f"  provider      : kakao")
        print(f"  provider_id   : test_user_001")
        print(f"  user_id       : {user_id}")

if __name__ == "__main__":
    main()
