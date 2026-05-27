from typing import Any

def get_profile(profile_name: str) -> dict[str, Any]:
    """
    요청된 테마 이름에 맞는 route profile dict를 반환한다.

    Profile은 사용자 의도/테마를 route_engine이 이해할 수 있는
    feature weight와 filter 규칙으로 표현한 데이터이다.

    예상 profile 구조:
    {
        "name": "quiet",
        "description": "조용하고 안전한 산책길",
        "weights": {
            "safety_score": 1.5,
            "nature_score": 1.2,
            "crowdedness_score": -1.0
        },
        "filters": {
            "avoid_road_types": ["highway"],
            "max_slope_score": None
        },
        "required_features": [
            "safety_score",
            "nature_score"
        ]
    }

    규칙:
    - `weights`의 key는 features/feature_registry.py의 표준 feature 이름과 일치해야 한다.
    - weight는 feature를 어떻게 해석할지만 표현한다.
    - graph edge를 직접 수정하지 않는다.

    금지:
    - graph 직접 수정 금지
    - custom_score 직접 계산 금지
    - circular/oneway engine 호출 금지
    - 외부 API 호출 금지
    - FastAPI, Streamlit, 기존 `src/service/route` import 금지

    TODO:
    - profile_name과 profile provider 함수의 매핑 테이블을 정의한다.
    - 알 수 없는 profile_name에 대한 fallback 정책을 정한다.
    - LLM이 생성한 dynamic profile을 받을 수 있는 구조를 검토한다.
    """
    pass
