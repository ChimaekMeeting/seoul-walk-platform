from typing import Any

def build_route_context(request: dict[str, Any]) -> dict[str, Any]:
    """
    날씨, 미세먼지, 주변 실시간 POI, 사용자 현재 위치 등을 하나의 Context 객체(dict)로 모은다.

    담당:
    - 외부 정보를 끌어와 라우팅 엔진이 참고할 수 있는 Context 로 포장.

    금지:
    - 외부 API (Kakao, 기상청 등) 직접 HTTP 호출 금지 (Infra 계층 위임)
    """
    pass
