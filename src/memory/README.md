# Memory Layer

## 1. 목적 및 역할
Memory 계층은 에이전트와 애플리케이션이 공통으로 사용하는 **상태(State), 선호도(Preference), 이력(History)** 데이터를 통합 관리하는 곳입니다.

## 2. 외부 저장소와의 차이
- **이 계층은 DB/Redis/ChromaDB 클라이언트가 아닙니다.**
- 데이터의 물리적인 적재(Save)와 조회(Load)는 `infrastructure` 계층의 DB나 Cache에 위임하며, Memory 계층은 이 저장소들을 호출하여 "어떻게 기억하고 언제 잊을지"에 대한 논리적 인터페이스만 제공합니다.

## 3. 금지사항
- 실제 SQLAlchemy, Redis, Valkey, ChromaDB 등의 연결 코드 구현 금지
- 실제 LLM 프롬프트 직접 조작 금지

## 4. 기억 범위
- `working_memory`: 현재 요청/짧은 세션의 임시 상태. cache 위임 대상.
- `chat_memory`: 대화 로그와 thread 상태. database 위임 대상.
- `user_preference_memory`: 장기 사용자 선호. database 또는 미래 semantic memory 위임 대상.
- `route_history_memory`: 추천 경로/완주/이탈 이력. database 위임 대상.
- `memory_policy`: 어떤 데이터를 cache/database/semantic/discard로 보낼지 판단하는 정책 위치.

현재 목표는 과거 기록 기반 고도화가 아니라, 한 루프 추천 이후 확장할 수 있도록 위치와 계약을 잡는 것입니다.
