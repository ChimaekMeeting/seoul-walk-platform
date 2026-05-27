# API Layer

**목적:** 프론트엔드가 호출할 REST API 라우터(Router)들이 위치할 공간입니다.

**금지사항:**
- 실제 FastAPI 프레임워크 구현 코드 삽입 금지.
- 실제 비즈니스 로직 작성 금지. 오직 `application` 계층을 호출하기 위한 어댑터로 설계합니다.

**원칙:**
- router는 얇아야 합니다.
- 요청 검증, application/agent 호출, 응답 포장만 담당합니다.
- React Native와 Streamlit prototype은 같은 API/UIEvent 계약을 사용합니다.
- 기존 `src/api/`는 현재 단계에서 건드리지 않습니다.
