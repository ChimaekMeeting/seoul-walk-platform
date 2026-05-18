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