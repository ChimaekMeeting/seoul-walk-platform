# Features (Layer 1)

**목적:** 길의 객관적 속성을 graph edge에 표준화된 이름으로 바인딩합니다. (예: `safety_score`, `nature_score`)

**금지사항:**
- `custom_score` 계산 금지
- 라우팅 알고리즘 호출 금지
- 외부 프레임워크(FastAPI, Streamlit) 임포트 금지
- 기존 중복 코드 임포트 금지
