from typing import Optional
from sqlalchemy import select

from src.database.postgresql import get_postgresql_db
from src.entity.route_history import RouteHistory
from src.interfaces.schema.walk_schema import WalkMode


class RouteHistoryRepository:
    @staticmethod
    def save(
        user_id: int,
        mode: WalkMode,
        origin_lat: float,
        origin_lon: float,
        coordinates: list,
        total_km: float,
        destination_lat: Optional[float] = None,
        destination_lon: Optional[float] = None,
    ) -> RouteHistory:
        with get_postgresql_db() as db:
            history = RouteHistory(
                user_id=user_id,
                mode=mode.value,
                origin_lat=origin_lat,
                origin_lon=origin_lon,
                destination_lat=destination_lat,
                destination_lon=destination_lon,
                coordinates=coordinates,
                total_km=total_km,
            )
            db.add(history)
            db.commit()
            db.refresh(history)
            return history

    @staticmethod
    def find_by_user_id(
        user_id: int,
        limit: int = 20,
        offset: int = 0,
        is_favorite: Optional[bool] = None,
    ) -> list[RouteHistory]:
        with get_postgresql_db() as db:
            query = select(RouteHistory).where(RouteHistory.user_id == user_id)
            if is_favorite is not None:
                query = query.where(RouteHistory.is_favorite == is_favorite)
            query = (
                query.order_by(RouteHistory.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            return list(db.execute(query).scalars().all())

    @staticmethod
    def find_by_id(history_id: int, user_id: int) -> Optional[RouteHistory]:
        with get_postgresql_db() as db:
            query = select(RouteHistory).where(
                RouteHistory.id == history_id,
                RouteHistory.user_id == user_id,
            )
            return db.execute(query).scalar_one_or_none()

    @staticmethod
    def toggle_favorite(history_id: int, user_id: int) -> Optional[RouteHistory]:
        with get_postgresql_db() as db:
            query = select(RouteHistory).where(
                RouteHistory.id == history_id,
                RouteHistory.user_id == user_id,
            )
            history = db.execute(query).scalar_one_or_none()
            if history is None:
                return None
            history.is_favorite = not history.is_favorite
            db.commit()
            db.refresh(history)
            return history
