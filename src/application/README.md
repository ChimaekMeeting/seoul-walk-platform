# Application Layer

## 1. 목적 및 역할
Application 계층은 API/router도 아니고 `route_engine`도 아닙니다.
이곳은 `domain` 계약과 `route_engine`을 이용해 **서비스 흐름을 조립(Orchestration)**하는 중앙 지휘소입니다.

## 2. 금지사항
- 외부 API 통신, DB 쿼리, LLM 직접 호출, 라우팅 알고리즘 수학 구현 등은 이 계층에서 **직접 구현하지 않습니다.**
- 오직 인프라/엔진/에이전트 계층을 호출하고 그 결과를 이어붙이는 파이프라인 역할만 수행합니다.

## 3. 타 계층과의 관계
- **Agent**: 추후 이 application 흐름 안에서 유저의 의도 파악 등 '판단'이 필요한 부분을 위임받습니다.
- **Frontend (Streamlit/React Native)**: 이 계층의 최종 결과물인 `UIEvent` 목록을 전달받아 수동적으로 화면에 렌더링만 수행합니다.
