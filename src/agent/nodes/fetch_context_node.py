from typing import Any

def fetch_context(state: dict[str, Any]) -> dict[str, Any]:
    """
    날씨, 미세먼지, 위치, live POI 등 필요한 context를 준비한다.

    실제 외부 API 호출은 tools 또는 infrastructure에 위임한다.
    """
    pass
