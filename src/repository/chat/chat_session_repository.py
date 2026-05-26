from src.database.postgresql import get_postgresql_db
from src.entity.chat_session import ChatSession, SessionState
from uuid import uuid4

class ChatSessionRepository:
    @staticmethod
    def save(user_id: int, thread_id: str, db=None) -> ChatSession:
        """
        db 세션이 주어지면 그대로 사용하고, 없으면 새로 생성하여 저장합니다.
        """
        if db is None:
            with get_postgresql_db() as new_db:
                return ChatSessionRepository.execute_save(new_db, user_id, thread_id)
        else:
            return ChatSessionRepository.execute_save(db, user_id, thread_id)

        
    @staticmethod
    def execute_save(db, user_id: int, thread_id: str) -> ChatSession:
        """
        실제 저장 로직을 담당하는 내부 메서드
        """
        session = ChatSession(
            user_id=user_id,
            current_state=SessionState.START,
            thread_id=thread_id
        )

        db.add(session)
        db.commit()
        db.refresh(session)

        return session
        
    @staticmethod
    def get_active_thread_id(user_id: int) -> str:
        with get_postgresql_db() as db:
            session = db.query(ChatSession).filter(
                ChatSession.user_id==user_id,
                ChatSession.current_state!=SessionState.COMPLETED
            ).order_by(ChatSession.updated_at.desc()).first()

            if not session:
                thread_id = str(uuid4())
                session = ChatSessionRepository.save(user_id, thread_id)

            return session.thread_id