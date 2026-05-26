from typing import Any, Literal

def classify_memory_target(data_type: str, payload: dict[str, Any]) -> Literal["cache", "database", "semantic", "discard"]:
    """
    데이터 종류에 따라 저장 위치를 결정하는 정책 함수 예정.

    예:
    - 현재 요청 상태 -> cache
    - 대화 로그 -> database
    - 장기 취향 요약 -> semantic
    - 일회성 raw API response -> discard 또는 short ttl cache

    현재 단계에서는 실제 정책 구현 금지.
    """
    pass

def get_memory_ttl_policy() -> dict[str, int]:
    """
    각종 메모리 데이터의 수명(TTL) 및 보존 정책을 정의하는 곳.
    예: working_memory는 1시간, chat_memory는 30일 등.

    금지:
    - 실제 Redis TTL 설정 명령 금지
    """
    pass
