from sqlalchemy import select
from src.database.postgresql import get_postgresql_db
from src.entity.user import User, Provider


class UserRepository:
    @staticmethod
    def save(provider: Provider, provider_id: str, nickname: str):
        """
        새 사용자를 저장합니다.
        """
        with get_postgresql_db() as db:
            new_user = User(
                provider=provider,
                provider_id=provider_id,
                nickname=nickname
            )

            db.add(new_user)
            db.commit()
            db.refresh(new_user)

            return new_user

    @staticmethod
    def find_by_provider_and_provider_id(provider: Provider, provider_id: str):
        """
        provider_id를 기반으로 사용자를 조회합니다.
        """
        with get_postgresql_db() as db:
            query = select(User).where(
                User.provider==provider,
                User.provider_id==provider_id
            )
            return db.execute(query).scalar_one_or_none()

    @staticmethod
    def update_nickname(provider: Provider, provider_id: str, nickname: str):
        """
        사용자의 닉네임을 수정합니다.
        """
        with get_postgresql_db() as db:
            query = select(User).where(
                User.provider==provider,
                User.provider_id==provider_id
            )
            user = db.execute(query).scalar_one_or_none()
            if user is None:
                return None
            user.nickname = nickname
            db.commit()
            db.refresh(user)
            return user
