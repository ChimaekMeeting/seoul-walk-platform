from sqlalchemy import select
from src.database.postgresql import get_postgresql_db
from src.entity.chat_session import ChatSession, SessionState
from uuid import uuid4


class ChatSessionRepository:
    @staticmethod
    def save(user_id: int, thread_id: str, db=None) -> ChatSession:
        """
        채팅 세션을 저장합니다.
        db 세션이 주어지면 그대로 사용하고, 없으면 새로 생성하여 저장합니다.

        Args:
            user_id   : 세션을 생성할 사용자 ID.
            thread_id : 채팅 스레드 식별자.
            db        : 외부에서 주입할 DB 세션. None이면 내부에서 새로 생성합니다.

        Returns:
            ChatSession: 저장된 세션 객체.
        """
        if db is None:
            with get_postgresql_db() as new_db:
                return ChatSessionRepository.execute_save(new_db, user_id, thread_id)
        else:
            return ChatSessionRepository.execute_save(db, user_id, thread_id)

    @staticmethod
    def execute_save(db, user_id: int, thread_id: str) -> ChatSession:
        """
        ChatSession 엔티티를 생성하고 DB에 커밋하는 내부 메서드입니다.

        Args:
            db        : 사용할 DB 세션.
            user_id   : 세션을 생성할 사용자 ID.
            thread_id : 채팅 스레드 식별자.

        Returns:
            ChatSession: refresh된 세션 객체.
        """
        session = ChatSession(
            user_id=user_id,
            current_state=SessionState.START,
            thread_id=thread_id,
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    @staticmethod
    def get_active_thread_id(user_id: int) -> str:
        """
        사용자의 활성 채팅 스레드 ID를 반환합니다.
        완료되지 않은 세션 중 가장 최근 세션을 조회하며,
        없으면 새 세션을 생성하고 해당 thread_id를 반환합니다.

        Args:
            user_id : 조회할 사용자 ID.

        Returns:
            str: 활성 thread_id.
        """
        with get_postgresql_db() as db:
            session = db.execute(
                select(ChatSession)
                .where(
                    ChatSession.user_id == user_id,
                    ChatSession.current_state != SessionState.COMPLETED,
                )
                .order_by(ChatSession.updated_at.desc())
            ).scalars().first()

            if not session:
                thread_id = str(uuid4())
                session = ChatSessionRepository.save(user_id, thread_id)

            return session.thread_id
        
    @staticmethod
    def find_by_thread_id(thread_id: str) -> ChatSession:
        """
        thread_id를 기반으로 ChatSession을 찾습니다.
        """
        with get_postgresql_db() as db:
            query = select(ChatSession).where(ChatSession.thread_id==thread_id)
            return db.execute(query).scalar_one_or_none()
