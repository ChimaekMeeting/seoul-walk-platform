from uuid import uuid4
from typing import Optional
from src.database.postgresql import get_postgresql_db
from src.entity.user import User

class UserRepository:
    @staticmethod
    def save(uuid: str):
        """
        사용자의 uuid를 저장합니다.
        """
        with get_postgresql_db() as db:
            new_user = User(uuid=uuid)
            db.add(new_user)
            db.commit()

    @staticmethod
    def get_id_by_uuid(uuid: str):
        """
        uuid를 기반으로 user.id를 반환합니다.
        """
        with get_postgresql_db() as db:
            user = db.query(User).filter_by(uuid=uuid).first()
            return user.id

    @staticmethod
    def get_by_provider_id(provider_id: int) -> Optional[User]:
        """
        카카오 provider_id로 사용자를 조회합니다.
        """
        with get_postgresql_db() as db:
            return db.query(User).filter_by(provider_id=provider_id).first()

    @staticmethod
    def save_kakao_user(provider_id: int, nickname: str, kakao_refresh_token: str) -> User:
        """
        카카오 로그인 사용자를 신규 저장합니다.
        """
        with get_postgresql_db() as db:
            user = User(
                uuid=str(uuid4()),
                provider_id=provider_id,
                nickname=nickname,
                kakao_refresh_token=kakao_refresh_token
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            return user

    @staticmethod
    def update_kakao_refresh_token(provider_id: int, kakao_refresh_token: str):
        """
        카카오 refresh_token을 갱신합니다.
        """
        with get_postgresql_db() as db:
            db.query(User).filter_by(provider_id=provider_id).update(
                {"kakao_refresh_token": kakao_refresh_token}
            )
            db.commit()