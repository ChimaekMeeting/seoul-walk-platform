from typing import Any

def start_prewalk_session(request: dict[str, Any]) -> list[Any]:
    """
    앱 최초 진입 시 초기 흐름을 조립한다.

    담당:
    - user 위치 수신 -> weather_context 생성 -> 초기 인사말 생성 -> UIEvent 목록 반환

    금지:
    - 외부 API(날씨 등) 직접 호출 금지. 다른 컴포넌트나 Infra 계층을 이용.
    """
    pass

def handle_user_message(thread_id: str, message: str) -> list[Any]:
    """
    사용자가 채팅 메시지를 보냈을 때의 전체 흐름을 조립한다.

    담당:
    - 메시지 수신 -> intent_service 로 의도 분석 -> (필요시) recommend_route_usecase 호출 -> response_builder 로 UIEvent 생성

    금지:
    - LLM 프롬프트 직접 조작 금지.
    """
    pass
