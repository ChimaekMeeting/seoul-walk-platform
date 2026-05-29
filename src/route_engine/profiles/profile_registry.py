from typing import Any

def get_profile(profile_name: str) -> dict[str, Any]:
    """
    요청된 테마 이름에 맞는 route profile dict를 반환합니다.

    Profile 구조 예시:
    {
        "name": "quiet",
        "weights": {"safety_score": 1.5, "nature_score": 1.2, "crowdedness_score": -1.0},
        "filters": {"avoid_road_types": ["highway"], "max_slope_score": None},
        "required_features": ["safety_score", "nature_score"]
    }

    규칙: weights의 key는 feature_registry.py의 표준 feature 이름과 일치해야 합니다.

    금지:
    - graph 직접 수정, custom_score 계산, circular/oneway engine 호출 금지
    - 외부 API 호출, FastAPI/Streamlit, 기존 src/service/route import 금지

    TODO:
    - profile_name과 provider 함수의 매핑 테이블을 정의합니다.
    - 알 수 없는 profile_name에 대한 fallback 정책을 정합니다.
    """
    pass
