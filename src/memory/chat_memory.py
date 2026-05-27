from typing import Any

def load_chat_history(session_id: str) -> list[dict[str, Any]]:
    """
    특정 세션의 대화 이력을 불러올 예정인 함수.

    예정 흐름:
    - infrastructure/repositories/chat_repository 또는 cache 계층에 위임

    금지:
    - 현재 단계에서 실제 DB/cache 호출 구현 금지
    """
    pass

def append_chat_message(session_id: str, role: str, content: str, metadata: dict[str, Any] | None = None) -> None:
    """
    사용자와 에이전트 간의 대화 내역(Chat History)을 추가한다.

    이후 흐름:
    - infrastructure/repositories/chat_repository 에 위임

    금지:
    - 실제 DB 쿼리문 작성 금지
    """
    pass

def get_chat_history(session_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """
    특정 세션의 대화 내역을 가져온다.

    호환용 skeleton:
    - 추후 `load_chat_history`로 통합할지 결정한다.
    """
    pass
