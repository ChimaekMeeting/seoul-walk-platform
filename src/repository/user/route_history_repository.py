import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from sqlalchemy import Integer, String, and_, case, cast, func, or_, select

from src.database.postgresql import get_postgresql_db
from src.entity.route_history import RouteHistory
from src.interfaces.schema.walk_schema import PlaceLabel, WalkMode, WalkProgressStatus
from src.repository.user.route_hash import create_route_hash

logger = logging.getLogger(__name__)

# 한국 표준시(UTC+9, 서머타임 없음). 타임존 데이터베이스에 기대지 않도록 고정 오프셋으로 둔다.
KST = timezone(timedelta(hours=9))


def today_kst() -> date:
    """한국 시간 기준 오늘 날짜(산책한 날짜 기록용)."""
    return datetime.now(KST).date()


def _group_key(group_by_route: bool):
    """같은 경로끼리 묶는 키(SQL 식). route_hash가 있으면 (버전, hash), 없는 행은 그 행 하나만의 그룹이다.
    group_by_route=False면 모든 행이 자기 자신만의 그룹이라 기존처럼 행 단위로 조회된다."""
    row_key = "row:" + cast(RouteHistory.id, String)
    if not group_by_route:
        return row_key
    return case(
        (RouteHistory.route_hash.is_(None), row_key),
        else_=func.coalesce(RouteHistory.route_hash_version, "") + ":" + RouteHistory.route_hash,
    )


def _same_route(history: RouteHistory):
    """이 이력과 같은 경로(같은 사용자, 같은 hash와 버전)인 행들의 조건. hash가 없으면 그 행 하나뿐이다."""
    if history.route_hash:
        return and_(
            RouteHistory.user_id == history.user_id,
            RouteHistory.route_hash == history.route_hash,
            RouteHistory.route_hash_version == history.route_hash_version,
        )
    return RouteHistory.id == history.id


def _route_hash_or_none(coordinates: list) -> tuple[Optional[str], Optional[str]]:
    """(route_hash, route_hash_version). 좌표가 없거나 계산에 실패하면 (None, None).

    hash는 부가 정보라 계산 실패가 이력 저장 실패로 이어지면 안 된다 — 사용자가 경로 id를 못 받는다."""
    try:
        if not coordinates:
            return None, None
        return create_route_hash(coordinates)
    except Exception as exc:
        logger.warning("route_hash_failed | error_type=%s", type(exc).__name__)
        return None, None


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
        route_hash, route_hash_version = _route_hash_or_none(coordinates)
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
                route_hash=route_hash,
                route_hash_version=route_hash_version,
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
    def find_page(
        user_id: int,
        walk_status: WalkProgressStatus = WalkProgressStatus.COMPLETED,
        is_favorite: Optional[bool] = None,
        limit: int = 20,
        offset: int = 0,
        group_by_route: bool = True,
    ) -> tuple[list[tuple[RouteHistory, bool]], int]:
        """기록 목록 한 페이지와 전체 그룹 수를 돌려준다. 각 원소는 (그룹 대표 행, 그룹의 즐겨찾기 여부).

        - 같은 경로(route_hash)의 행은 한 그룹이고, 대표 행 하나만 나온다. limit/offset/total도 그룹 기준이다.
          group_by_route=False면 행 하나가 한 그룹이라 기존처럼 행 단위로 나온다.
        - is_favorite=True(즐겨찾기 탭)는 진행 상태를 거르지 않는다. 그 외에는 walk_status로 거른다:
          completed는 완주 행과 상태 컬럼이 생기기 전의 행(walk_status NULL), in_progress는 진행 중인 행.
        - 그룹의 즐겨찾기 여부는 같은 경로의 행 중 하나라도 즐겨찾기인지(상태로 거르기 전 전체 행 기준)다.
        - 정렬: completed와 즐겨찾기는 walked_on 최신순(없으면 뒤), 같으면 created_at, id 최신순.
          in_progress는 created_at, id 최신순(시작 시각을 저장하지 않는다). 대표 행도 같은 순서의 첫 행이다.
        """
        group_key = _group_key(group_by_route)
        base = (
            select(
                RouteHistory.id.label("id"),
                group_key.label("gk"),
                RouteHistory.walk_status.label("walk_status"),
                RouteHistory.walked_on.label("walked_on"),
                RouteHistory.created_at.label("created_at"),
                func.max(cast(func.coalesce(RouteHistory.is_favorite, False), Integer))
                .over(partition_by=group_key)
                .label("fav_any"),
            )
            .where(RouteHistory.user_id == user_id)
            .subquery("base")
        )

        favorites_tab = is_favorite is True
        conditions = []
        if not favorites_tab:
            if walk_status == WalkProgressStatus.COMPLETED:
                conditions.append(or_(
                    base.c.walk_status == WalkProgressStatus.COMPLETED.value, base.c.walk_status.is_(None),
                ))
            else:
                conditions.append(base.c.walk_status == walk_status.value)
        if is_favorite is True:
            conditions.append(base.c.fav_any > 0)
        elif is_favorite is False:
            conditions.append(base.c.fav_any == 0)

        if favorites_tab or walk_status == WalkProgressStatus.COMPLETED:
            order = [base.c.walked_on.desc().nulls_last(), base.c.created_at.desc(), base.c.id.desc()]
        else:
            order = [base.c.created_at.desc(), base.c.id.desc()]

        ranked = (
            select(
                base.c.id, base.c.gk, base.c.fav_any, base.c.walked_on, base.c.created_at,
                func.row_number().over(partition_by=base.c.gk, order_by=order).label("rn"),
            )
            .where(*conditions)
            .subquery("ranked")
        )
        if favorites_tab or walk_status == WalkProgressStatus.COMPLETED:
            page_order = [ranked.c.walked_on.desc().nulls_last(), ranked.c.created_at.desc(), ranked.c.id.desc()]
        else:
            page_order = [ranked.c.created_at.desc(), ranked.c.id.desc()]

        with get_postgresql_db() as db:
            total = db.execute(select(func.count()).select_from(ranked).where(ranked.c.rn == 1)).scalar_one()
            representatives = db.execute(
                select(ranked.c.id, ranked.c.fav_any)
                .where(ranked.c.rn == 1)
                .order_by(*page_order)
                .limit(limit)
                .offset(offset)
            ).all()
            ids = [row.id for row in representatives]
            histories = (
                {h.id: h for h in db.execute(select(RouteHistory).where(RouteHistory.id.in_(ids))).scalars().all()}
                if ids else {}
            )
            return [(histories[row.id], bool(row.fav_any)) for row in representatives], total

    @staticmethod
    def is_group_favorite(history_id: int, user_id: int) -> Optional[bool]:
        """이 이력과 같은 경로의 행 중 하나라도 즐겨찾기인지. 이력이 없거나 다른 사용자의 것이면 None."""
        with get_postgresql_db() as db:
            history = db.execute(
                select(RouteHistory).where(RouteHistory.id == history_id, RouteHistory.user_id == user_id)
            ).scalar_one_or_none()
            if history is None:
                return None
            favorite = db.execute(
                select(func.max(cast(func.coalesce(RouteHistory.is_favorite, False), Integer)))
                .where(_same_route(history))
            ).scalar_one()
            return bool(favorite)

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
            # 같은 경로(route_hash)의 모든 행에 적용한다. 목록이 같은 경로를 한 항목으로 묶어 보여 주므로,
            # 대표 행만 바꾸면 다른 행에 남은 즐겨찾기 때문에 해제해도 계속 즐겨찾기로 보인다.
            same_route = db.execute(select(RouteHistory).where(_same_route(history))).scalars().all()
            new_value = not any(row.is_favorite for row in same_route)
            for row in same_route:
                row.is_favorite = new_value
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
        시작을 누르지 않은 기록도 완주로 기록할 수 있다. 이미 완주한 기록도 다시 완주로 기록하면 walked_on을
        그 날짜로 덮어쓴다 — 재산책이 최근 산책 순서에 반영되게 하기 위해서이며, 최초 완주일은 남기지 않는다.
        같은 날 여러 번 호출해도 결과는 같다. 기록이 없거나 다른 사용자의 것이면 None."""
        with get_postgresql_db() as db:
            query = select(RouteHistory).where(
                RouteHistory.id == history_id,
                RouteHistory.user_id == user_id,
            )
            history = db.execute(query).scalar_one_or_none()
            if history is None:
                return None
            history.walk_status = WalkProgressStatus.COMPLETED.value
            history.walked_on = walked_on or today_kst()
            db.commit()
            db.refresh(history)
            return history
