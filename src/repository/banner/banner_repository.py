from sqlalchemy import select
from src.database.postgresql import get_postgresql_db
from src.entity.banner import Banner


_SEED_DATA = [
    {
        "key": "hot_sunny", "category": "season",
        "emoji": "🌳", "text": "오늘 덥죠? 그늘 가득한 숲길 어떠세요?", "sub": "더위를 피하는 나만의 산책 코스",
        "scoring": {"mode": "general", "weights": {"safety": 1.0, "nature": 2.5, "slope": 2.0, "landmark": 0.0, "child": 0.0, "running": 0.0}, "blocked_tags": []},
    },
    {
        "key": "hot_humid", "category": "season",
        "emoji": "🌊", "text": "습한 날엔 물가 바람이 최고예요", "sub": "시원한 물가 코스 추천",
        "scoring": {"mode": "general", "weights": {"safety": 1.0, "nature": 2.0, "slope": 1.5, "landmark": 0.5, "child": 0.0, "running": 0.0}, "blocked_tags": []},
    },
    {
        "key": "hot_morning", "category": "season",
        "emoji": "🌅", "text": "더워지기 전에 먼저 걸어볼까요?", "sub": "상쾌한 새벽 산책 코스",
        "scoring": {"mode": "general", "weights": {"safety": 1.5, "nature": 1.5, "slope": 1.5, "landmark": 0.0, "child": 0.0, "running": 0.0}, "blocked_tags": []},
    },
    {
        "key": "dog", "category": "fixed",
        "emoji": "🐶", "text": "강아지랑 함께 걷기 좋은 길이에요", "sub": "반려견 동반 가능 코스",
        "scoring": {"mode": "general", "weights": {"safety": 2.0, "nature": 1.0, "slope": 1.5, "landmark": 0.0, "child": 2.0, "running": 0.0}, "blocked_tags": []},
    },
    {
        "key": "healing", "category": "fixed",
        "emoji": "🌿", "text": "조용하게 걷고 싶을 때 추천해요", "sub": "힐링 숲길 코스",
        "scoring": {"mode": "general", "weights": {"safety": 1.5, "nature": 2.5, "slope": 2.0, "landmark": 0.0, "child": 0.0, "running": 0.0}, "blocked_tags": []},
    },
    {
        "key": "night", "category": "fixed",
        "emoji": "🌃", "text": "저녁에 걷기 좋은 야경 코스예요", "sub": "야경 명소 산책로",
        "scoring": {"mode": "general", "weights": {"safety": 2.0, "nature": 0.5, "slope": 1.0, "landmark": 3.0, "child": 0.0, "running": 0.0}, "blocked_tags": []},
    },
]


class BannerRepository:
    @staticmethod
    def find_all() -> list[Banner]:
        with get_postgresql_db() as db:
            return db.execute(select(Banner)).scalars().all()

    @staticmethod
    def find_by_key(key: str) -> Banner | None:
        with get_postgresql_db() as db:
            return db.execute(select(Banner).where(Banner.key == key)).scalar_one_or_none()

    @staticmethod
    def seed():
        with get_postgresql_db() as db:
            if db.execute(select(Banner)).first():
                return
            for data in _SEED_DATA:
                db.merge(Banner(**data))
            db.commit()
