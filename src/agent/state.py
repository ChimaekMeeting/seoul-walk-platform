from typing import Any

class AgentState:
    """
    Agent workflow에서 공유할 상태 계약(State Contract) Skeleton.

    예상 필드:
    - thread_id: str
    - user_id: str
    - user_message: str
    - extracted_intent: dict[str, Any]
    - route_request: dict[str, Any]
    - route_context: dict[str, Any]
    - route_result: Any
    - ui_events: list[Any]
    - memory_context: dict[str, Any]
    - errors: list[str]

    금지:
    - 실제 dataclass/Pydantic 구현 금지.
    """
    thread_id: str | None
    user_id: str | None
    user_message: str | None
    extracted_intent: dict[str, Any] | None
    route_request: dict[str, Any] | None
    route_context: dict[str, Any] | None
    route_result: dict[str, Any] | None
    ui_events: list[dict[str, Any]]
    memory_context: dict[str, Any]
    errors: list[str]

    pass
