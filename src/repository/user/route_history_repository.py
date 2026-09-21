from datetime import date, datetime, timedelta, timezone
from typing import Optional
from sqlalchemy import select

from src.database.postgresql import get_postgresql_db
from src.entity.route_history import RouteHistory
from src.interfaces.schema.walk_schema import PlaceLabel, WalkMode, WalkProgressStatus

# 한국 표준시(UTC+9, 서머타임 없음). 타임존 데이터베이스에 기대지 않도록 고정 오프셋으로 둔다.
KST = timezone(timedelta(hours=9))


def today_kst() -> date:
    """한국 시간 기준 오늘 날짜(산책한 날짜 기록용)."""
    return datetime.now(KST).date()


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
        candidate_features: Optional[list] = None,
        origin_label: Optional[PlaceLabel] = None,
        destination_label: Optional[PlaceLabel] = None,
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
                candidate_features=candidate_features,
                origin_address=origin_label.address if origin_label else None,
                origin_place_name=origin_label.place_name if origin_label else None,
                destination_address=destination_label.address if destination_label else None,
                destination_place_name=destination_label.place_name if destination_label else None,
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

    @staticmethod
    def mark_started(history_id: int, user_id: int) -> Optional[RouteHistory]:
        """산책 시작을 기록한다(recommended -> in_progress). 이미 진행 중이거나 완주한 기록은 상태를
        되돌리지 않고 그대로 돌려준다. 기록이 없거나 다른 사용자의 것이면 None."""
        with get_postgresql_db() as db:
            query = select(RouteHistory).where(
                RouteHistory.id == history_id,
                RouteHistory.user_id == user_id,
            )
            history = db.execute(query).scalar_one_or_none()
            if history is None:
                return None
            # walk_status가 없던 시절의 기록은 NULL이라 recommended로 본다.
            if history.walk_status in (None, WalkProgressStatus.RECOMMENDED.value):
                history.walk_status = WalkProgressStatus.IN_PROGRESS.value
                db.commit()
                db.refresh(history)
            return history

    @staticmethod
    def mark_completed(
        history_id: int, user_id: int, walked_on: Optional[date] = None,
    ) -> Optional[RouteHistory]:
        """완주를 기록한다(-> completed). 완주한 날짜(walked_on, 기본은 한국 시간 오늘)를 함께 저장한다.
        시작을 누르지 않은 기록도 완주로 기록할 수 있고, 이미 완주한 기록은 날짜를 바꾸지 않는다(멱등).
        기록이 없거나 다른 사용자의 것이면 None."""
        with get_postgresql_db() as db:
            query = select(RouteHistory).where(
                RouteHistory.id == history_id,
                RouteHistory.user_id == user_id,
            )
            history = db.execute(query).scalar_one_or_none()
            if history is None:
                return None
            if history.walk_status != WalkProgressStatus.COMPLETED.value:
                history.walk_status = WalkProgressStatus.COMPLETED.value
                history.walked_on = walked_on or today_kst()
                db.commit()
                db.refresh(history)
            return history
