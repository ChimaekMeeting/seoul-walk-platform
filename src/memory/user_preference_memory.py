from typing import Any

def load_user_preferences(user_id: str) -> dict[str, Any]:
    """
    사용자 선호 정보를 불러올 예정인 함수.

    예:
    - 조용한 길 선호
    - 평지 선호
    - 공원/하천 선호
    - 야간 안전 민감도

    금지:
    - 현재 단계에서 DB/vector DB query 구현 금지
    """
    pass

def update_user_preference(user_id: str, extracted_preference: dict[str, Any]) -> None:
    """
    대화를 통해 파악된 사용자의 장기적인 선호도(예: "나는 평지가 좋아", "조용한 곳 선호")를 업데이트한다.

    담당:
    - 명시적이거나 암묵적인 선호 정보 병합

    이후 흐름:
    - infrastructure/repositories/user_repository 에 위임

    금지:
    - 실제 Vector DB(ChromaDB)나 RDB 쿼리 구현 금지
    """
    pass

def get_user_preference(user_id: str) -> dict[str, Any]:
    """
    사용자의 장기 선호도 정보를 로드하여 반환한다.

    호환용 skeleton:
    - 추후 `load_user_preferences`로 통합할지 결정한다.
    """
    pass

def update_user_preferences(user_id: str, preference_delta: dict[str, Any]) -> None:
    """
    사용자 선호 변화량을 저장할 예정인 함수.

    금지:
    - 현재 단계에서 DB/vector DB query 구현 금지
    """
    pass
