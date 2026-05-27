from sqlalchemy import select
from src.database.postgresql import get_postgresql_db
from src.entity.user import User


class UserRepository:
    @staticmethod
    def save(uuid: str):
        """
        새 사용자를 users 테이블에 저장합니다.

        Args:
            uuid : 저장할 사용자의 고유 식별자.
        """
        with get_postgresql_db() as db:
            new_user = User(uuid=uuid)
            db.add(new_user)
            db.commit()

    @staticmethod
    def get_id_by_uuid(uuid: str):
        """
        uuid를 기반으로 users 테이블의 PK(id)를 반환합니다.

        Args:
            uuid : 조회할 사용자의 고유 식별자.

        Returns:
            int | None: 사용자의 id. 존재하지 않으면 None.
        """
        with get_postgresql_db() as db:
            return db.execute(
                select(User.id).where(User.uuid == uuid)
            ).scalar_one_or_none()
