"""
src/repository/user/route_feedback_repository.py

RouteFeedback 엔티티에 대한 DB 접근을 담당하는 리포지토리.
"""
from sqlalchemy import select

from src.database.postgresql import get_postgresql_db
from src.entity.route_feedback import RouteFeedback


class RouteFeedbackRepository:
    @staticmethod
    def upsert(
        user_id: int,
        route_history_id: int,
        rating_safety: int,
        rating_comfort: int,
        rating_overall: int,
    ) -> RouteFeedback:
        """
        route_history_id 기준으로 피드백을 생성하거나(최초 제출) 갱신합니다(재제출).
        """
        with get_postgresql_db() as db:
            query = select(RouteFeedback).where(RouteFeedback.route_history_id == route_history_id)
            feedback = db.execute(query).scalar_one_or_none()

            if feedback is None:
                feedback = RouteFeedback(
                    user_id=user_id,
                    route_history_id=route_history_id,
                    rating_safety=rating_safety,
                    rating_comfort=rating_comfort,
                    rating_overall=rating_overall,
                )
                db.add(feedback)
            else:
                feedback.rating_safety = rating_safety
                feedback.rating_comfort = rating_comfort
                feedback.rating_overall = rating_overall

            db.commit()
            db.refresh(feedback)
            return feedback

    @staticmethod
    def find_by_route_history_id(route_history_id: int) -> RouteFeedback | None:
        with get_postgresql_db() as db:
            query = select(RouteFeedback).where(RouteFeedback.route_history_id == route_history_id)
            return db.execute(query).scalar_one_or_none()
