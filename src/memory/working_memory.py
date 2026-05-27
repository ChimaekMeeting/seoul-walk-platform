from typing import Any

class WorkingMemory:
    """
    현재 agent/application 실행 중에만 필요한 임시 상태 계약.

    저장 대상:
    - 현재 사용자 메시지
    - 이번 요청의 intent
    - 이번 요청의 route context
    - 이번 요청의 route result
    - 이번 응답의 UIEvent 후보

    금지:
    - 실제 Redis/Valkey 연결 구현 금지
    - DB query 구현 금지
    """
    session_id: str | None
    current_intent: dict[str, Any] | None
    current_route_request: dict[str, Any] | None
    current_route_context: dict[str, Any] | None
    current_route_result: dict[str, Any] | None
    current_ui_events: list[dict[str, Any]]
    temporary_notes: dict[str, Any]

    pass

def save_working_memory(session_id: str, key: str, value: Any) -> None:
    """
    단일 요청(Request)이나 짧은 세션 동안만 유지되는 임시 작업 기억을 저장한다.

    담당:
    - 요청 주기 동안 유지되어야 하는 계산 중간값, 임시 컨텍스트 저장

    이후 흐름:
    - infrastructure/cache/cache_client 에 위임

    금지:
    - 실제 Redis/Valkey 등 연결 코드 작성 금지
    """
    pass

def load_working_memory(session_id: str, key: str) -> Any:
    """
    임시 작업 기억을 로드한다.
    """
    pass
