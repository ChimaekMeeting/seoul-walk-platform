from typing import Any

def get_cache(key: str) -> Any:
    """
    cache 조회 예정 함수.

    담당:
    - 짧은 TTL의 임시 데이터 조회
    - 예: weather:{lat}:{lon}, live_poi:{lat}:{lon}:{category}

    금지:
    - 현재 단계에서 Redis/Valkey 실제 연결 구현 금지
    - 영구 저장소처럼 사용하는 구조 금지
    """
    pass

def set_cache(key: str, value: Any, ttl_seconds: int | None = None) -> None:
    """
    cache 저장 예정 함수.

    담당:
    - 날씨/미세먼지/실시간 POI raw 또는 표준화 context를 짧게 저장할 예정

    주의:
    - ttl_seconds가 없는 무기한 저장은 기본 정책으로 금지하는 것이 좋다.

    금지:
    - 현재 단계에서 Redis/Valkey 실제 연결 구현 금지
    """
    pass
