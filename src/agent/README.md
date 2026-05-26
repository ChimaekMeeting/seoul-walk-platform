# Agent Layer

## 1. 목적 및 역할
Agent는 LLM(대형 언어 모델) 기반의 판단 계층입니다. 사용자의 자연어 의도를 해석하고, 필요한 context를 결정하며, 알맞은 tool을 호출하여 응답을 조립하는 지휘자 역할을 합니다.

## 2. 위치
- Agent는 `application` 계층 흐름 안에서 호출될 수 있는 독립적인 워크플로우 단위입니다.

## 3. 금지사항
- Agent는 `route_engine`의 알고리즘(수학적 그래프 연산)을 직접 구현하지 않고, 오직 `route_tool`을 통해 호출만 합니다.
- Agent는 외부 API(Kakao, Weather)나 DB/cache를 직접 호출하지 않습니다. `tools`, `infrastructure`, `context` 흐름을 거쳐서 데이터를 가져옵니다.
- Agent는 프론트엔드 UI를 직접 렌더링하지 않으며, 단지 렌더링할 `UIEvent` 후보를 결정합니다.
- 현재 단계에서는 실제 LangGraph/LangChain/OpenAI 등의 서드파티 라이브러리 구현 코드를 넣지 않습니다.

## 4. 확장성
- 추후 실제 워크플로우 엔진을 LangGraph나 LangChain으로 교체하더라도, 현재 정의된 `nodes`와 `tools` 계약의 껍데기는 변하지 않고 유지되어야 합니다.
