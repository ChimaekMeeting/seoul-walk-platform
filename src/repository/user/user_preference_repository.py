"""
src/repository/user/user_preference_repository.py

UserPreference 엔티티에 대한 DB 접근을 담당하는 리포지토리.
"""
from sqlalchemy import select

from src.database.postgresql import get_postgresql_db
from src.entity.user_preference import UserPreference


class UserPreferenceRepository:
    """
    user_preferences 테이블에 대한 CRUD를 담당합니다.
    """

    @staticmethod
    def upsert(user_id: int, **kwargs) -> UserPreference:
        """
        user_id 기준으로 선호도 레코드를 생성하거나 갱신합니다.
        레코드가 없으면 INSERT, 있으면 kwargs 필드만 UPDATE합니다.
        """
        with get_postgresql_db() as db:
            query = select(UserPreference).where(UserPreference.user_id == user_id)
            preference = db.execute(query).scalar_one_or_none()

            if preference is None:
                preference = UserPreference(user_id=user_id, **kwargs)
                db.add(preference)
            else:
                for key, value in kwargs.items():
                    setattr(preference, key, value)

            db.commit()
            db.refresh(preference)
            return preference
