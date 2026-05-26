# Seoul Walk Platform Agentic Backend Architecture Plan

> 목적: 지금 당장 기능 코드를 구현하는 문서가 아니라, 팀 분업과 이후 리팩토링 방향을 맞추기 위한 패키지 구조 설명 문서입니다.
>
> 현재 Streamlit `app.py`는 구현 검증용 프로토타입이며, 최종 서비스는 React Native 앱 + FastAPI 백엔드 구조를 목표로 합니다.

---

## 1. 핵심 결론

이 프로젝트는 단순 FastAPI CRUD 서버도 아니고, 단순 LLM 챗봇도 아닙니다.

우리가 만들려는 것은 다음 세 가지가 결합된 서비스입니다.

```text
React Native App / Streamlit Prototype
        |
FastAPI Backend
        |
Geo AI Agentic Route Recommendation System
```

따라서 패키지 구조도 세 관점을 모두 만족해야 합니다.

1. **앱 백엔드 관점**
   - 프론트엔드는 API를 호출하고 결과를 렌더링합니다.
   - Streamlit은 임시 검증용 클라이언트이며, 나중에 React Native로 교체됩니다.

2. **클린 아키텍처 관점**
   - API, usecase, domain, DB, external client를 섞지 않습니다.
   - FastAPI 라우터에 비즈니스 로직을 넣지 않습니다.

3. **에이전틱 아키텍처 관점**
   - LLM은 사용자 의도를 이해하고 필요한 tool을 선택합니다.
   - 라우팅 엔진은 LLM과 독립적으로 순수하게 경로를 계산합니다.
   - 날씨, 미세먼지, 주변 POI, 사용자 위치 등은 agent context로 조립됩니다.

---

## 2. 전체 권장 패키지 구조

```text
seoul-walk-platform/
│
├── backend/
│   └── src/
│       ├── main.py
│       │
│       ├── api/
│       │   ├── prewalk_router.py
│       │   ├── route_router.py
│       │   ├── weather_router.py
│       │   └── poi_router.py
│       │
│       ├── application/
│       │   ├── prewalk/
│       │   │   ├── prewalk_orchestrator.py
│       │   │   ├── intent_service.py
│       │   │   └── response_builder.py
│       │   ├── route_recommendation/
│       │   │   ├── recommend_route_usecase.py
│       │   │   └── route_context_builder.py
│       │   └── ui_events/
│       │       ├── ui_event_schema.py
│       │       └── ui_event_builder.py
│       │
│       ├── agent/
│       │   ├── walk_agent.py
│       │   ├── state.py
│       │   ├── nodes/
│       │   │   ├── extract_intent_node.py
│       │   │   ├── fetch_context_node.py
│       │   │   ├── recommend_route_node.py
│       │   │   └── build_response_node.py
│       │   └── tools/
│       │       ├── weather_tool.py
│       │       ├── poi_tool.py
│       │       └── route_tool.py
│       │
│       ├── domain/
│       │   ├── route/
│       │   │   ├── route_request.py
│       │   │   ├── route_result.py
│       │   │   ├── feature_spec.py
│       │   │   └── profile.py
│       │   ├── user/
│       │   └── chat/
│       │
│       ├── route_engine/
│       │   ├── graph/
│       │   │   ├── graph_loader.py
│       │   │   ├── graph_filter.py
│       │   │   └── graph_serializer.py
│       │   ├── features/
│       │   │   ├── feature_registry.py
│       │   │   ├── base_feature.py
│       │   │   ├── safety_features.py
│       │   │   ├── nature_features.py
│       │   │   ├── slope_features.py
│       │   │   ├── landmark_features.py
│       │   │   └── live_poi_features.py
│       │   ├── profiles/
│       │   │   ├── profile_registry.py
│       │   │   ├── base_profile.py
│       │   │   ├── quiet_profile.py
│       │   │   ├── running_profile.py
│       │   │   ├── child_profile.py
│       │   │   └── flat_profile.py
│       │   ├── scoring/
│       │   │   └── scoring_engine.py
│       │   ├── engines/
│       │   │   ├── circular_engine.py
│       │   │   └── oneway_engine.py
│       │   ├── result/
│       │   │   └── route_result_builder.py
│       │   └── route_orchestrator.py
│       │
│       ├── context/
│       │   ├── weather_context.py
│       │   ├── air_quality_context.py
│       │   ├── live_poi_context.py
│       │   └── user_location_context.py
│       │
│       ├── memory/
│       │   ├── chat_memory.py
│       │   ├── user_preference_memory.py
│       │   └── route_history_memory.py
│       │
│       ├── infrastructure/
│       │   ├── db/
│       │   │   ├── entities/
│       │   │   └── session.py
│       │   ├── repositories/
│       │   ├── external/
│       │   │   ├── kakao_client.py
│       │   │   ├── weather_client.py
│       │   │   └── gpt_client.py
│       │   └── cache/
│       │
│       ├── schemas/
│       ├── prompts/
│       └── config/
│
├── frontend/
│   ├── streamlit_prototype/
│   │   ├── app.py
│   │   ├── api_client.py
│   │   ├── state.py
│   │   └── components/
│   │       ├── chat_panel.py
│   │       ├── map_view.py
│   │       ├── weather_card.py
│   │       ├── route_summary.py
│   │       ├── poi_overlay.py
│   │       └── banner_carousel.py
│   └── mobile_app/
│       └── README.md
│
├── data/
│   ├── raw/
│   ├── processed/
│   ├── collectors/
│   └── migrations/
│
├── scripts/
├── docs/
└── tests/
```

---

## 3. 이 구조는 에이전틱 구조인가, 클린 아키텍처인가?

둘 다입니다. 더 정확히 말하면:

```text
api / application / domain / infrastructure / schemas
```

이 부분은 FastAPI 백엔드에서 자주 쓰는 **Clean Architecture / Hexagonal Architecture** 계열 구조입니다.

반면 아래 부분은 이 프로젝트의 에이전틱 성격 때문에 추가된 구조입니다.

```text
agent/
tools/
memory/
context/
route_engine/
prompts/
```

즉 이 레포는 다음 구조를 조합합니다.

```text
FastAPI Clean Architecture
+ Agentic Workflow
+ Geo Routing Engine
+ App Client Architecture
```

---

## 4. 각 폴더의 역할

### `api/`

프론트엔드가 호출하는 HTTP 입구입니다.

예:

```text
POST /api/prewalk/init
POST /api/prewalk/message
POST /api/routes/recommend
GET  /api/weather
GET  /api/poi/nearby
```

이 계층은 얇아야 합니다.

해야 할 일:

- 요청 schema 검증
- application usecase 호출
- 응답 반환

하지 말아야 할 일:

- NetworkX 경로 계산
- GPT 프롬프트 직접 호출
- DB query 직접 작성
- 카카오맵 API 직접 호출
- 복잡한 if/else 서비스 흐름 작성

---

### `application/`

서비스 흐름을 조립하는 계층입니다.

예를 들어 사용자가 앱을 켰을 때:

```text
현재 위치 수신
-> 날씨/미세먼지 조회
-> 초기 추천 문구 생성
-> 필요한 UI event 생성
-> 프론트에 반환
```

사용자가 채팅을 입력했을 때:

```text
사용자 메시지 수신
-> 의도 분석
-> context 수집
-> route_engine 호출
-> 응답 문구/지도/추천 카드 생성
-> 프론트에 반환
```

여기에는 LLM을 반드시 써야 하는 것은 아닙니다.
명시적인 코드 흐름으로 처리 가능한 usecase는 `application/`에 둡니다.

---

### `agent/`

LLM이 개입하는 판단 루프입니다.

예:

```text
사용자: 사람 적고 예쁜 길로 3km 걷고 싶어
-> extract_intent_node
-> fetch_context_node
-> recommend_route_node
-> build_response_node
```

`agent/tools/`는 LLM이 호출할 수 있는 도구입니다.

```text
weather_tool.py  -> 날씨 조회
poi_tool.py      -> 주변 편의시설 조회
route_tool.py    -> route_engine 호출
```

중요한 원칙:

- Agent는 경로 알고리즘을 직접 구현하지 않습니다.
- Agent는 route_engine을 tool로 호출합니다.
- Agent는 어떤 profile을 쓸지, 어떤 설명을 붙일지 판단합니다.

---

### `domain/`

프레임워크, DB, 외부 API와 독립적인 핵심 개념입니다.

예:

```text
RouteRequest
RouteResult
FeatureSpec
Profile
UserPreference
ChatState
```

이 계층은 가능하면 순수 Python/Pydantic 모델에 가깝게 둡니다.
FastAPI, SQLAlchemy, Kakao API 응답 형식에 강하게 묶이지 않도록 합니다.

---

### `route_engine/`

이 프로젝트의 핵심 라우팅 코어입니다.

Gemini와 논의한 3-Layer 구조는 이 폴더에 들어갑니다.

```text
features  -> 길의 객관적 속성
profiles  -> 사용자 의도/테마별 해석
scoring   -> feature * profile 계산
engines   -> 순환/편도 경로 알고리즘
```

핵심 원칙:

- LLM에 의존하지 않습니다.
- Streamlit/React Native에 의존하지 않습니다.
- FastAPI request 객체에 의존하지 않습니다.
- 입력으로 그래프, 위치, 거리, profile을 받고 경로 결과를 반환합니다.

---

## 5. Route Engine 3-Layer 상세 구조

### Layer 1: `features/`

길의 객관적 속성을 관리합니다.

예:

```text
safety_score
nature_score
slope_score
landmark_score
cctv_density
park_accessibility
river_accessibility
```

중요한 해석:

`features/`는 매 요청마다 원천 데이터를 새로 계산하는 함수만 의미하지 않습니다.

정적 데이터는 미리 DB에 materialize하고, 런타임에서는 GraphLoader가 이를 edge attribute로 읽어옵니다.

```text
정적 Layer 1:
  CCTV, 경찰서, 공원, 하천, 경사도, 랜드마크
  -> 배치/collector로 DB에 저장
  -> 런타임에 graph edge attribute로 로드

실시간 Layer 1.5:
  카카오맵 주변 편의시설, 현재 날씨, 미세먼지
  -> 요청 시점에 외부 API로 조회
  -> route context 또는 overlay feature로 사용
```

즉 최종 목표는 내부적으로는 분리하되, 사용자 화면에는 자연스럽게 합쳐서 보여주는 것입니다.

---

### Layer 2: `profiles/`

사용자 의도나 테마를 가중치/필터 규칙으로 바꿉니다.

예:

```text
quiet_profile:
  safety_score: 1.8
  nature_score: 1.2
  crowdedness_score: -1.5

running_profile:
  slope_score: 1.5
  path_width_score: 1.3
  traffic_light_penalty: 1.2

child_profile:
  safety_score: 2.0
  slope_score: 1.2
  school_zone_score: 1.5
```

Profile은 고정 테마일 수도 있고, LLM이 사용자 문장에서 만든 dynamic profile일 수도 있습니다.

---

### Layer 3: `scoring/` + `engines/`

`scoring_engine.py`는 그래프의 feature와 profile weight를 결합해 최종 edge cost를 만듭니다.

예:

```text
edge features:
  safety_score = 0.8
  nature_score = 0.6
  slope_score = 0.9

profile weights:
  safety_score = 1.5
  nature_score = 1.2
  slope_score = 0.7

scoring_engine:
  custom_score 계산
```

이후 `circular_engine.py`, `oneway_engine.py`가 `custom_score`를 사용해 실제 경로를 찾습니다.

---

## 6. Context 계층

`context/`는 순수 클린 아키텍처의 표준 폴더라기보다, 이 서비스에 필요한 에이전트 판단 재료입니다.

예:

```text
weather_context.py
air_quality_context.py
live_poi_context.py
user_location_context.py
```

이 계층은 다음 정보를 모읍니다.

- 현재 위치
- 현재 날씨
- 미세먼지
- 시간대
- 주변 편의시설
- 사용자 입력에서 추출된 선호/기피 조건

Route recommendation은 단순히 도로망만 보고 결정하지 않습니다.
현재 상황을 함께 봐야 하므로 context 계층이 필요합니다.

---

## 7. Infrastructure 계층

`infrastructure/`는 바깥 세계와 연결되는 구현부입니다.

```text
infrastructure/db/
  PostgreSQL, PostGIS, SQLAlchemy session, entity

infrastructure/repositories/
  DB query 구현체

infrastructure/external/
  kakao_client.py
  weather_client.py
  gpt_client.py

infrastructure/cache/
  Redis/Valkey
```

중요한 원칙:

- application/domain/route_engine은 외부 API의 raw response에 직접 의존하지 않습니다.
- external client가 raw response를 받아오고, context/application 계층에서 내부 모델로 변환합니다.

---

## 8. Schemas와 Domain의 차이

`schemas/`는 API로 들어오고 나가는 JSON 모양입니다.

`domain/`은 서비스 내부의 핵심 개념입니다.

예:

```text
schemas/route_schema.py
  RecommendRouteRequest
  RecommendRouteResponse

domain/route/route_request.py
  RouteRequest

domain/route/route_result.py
  RouteResult
```

초기에는 둘이 거의 같아도 됩니다.
하지만 장기적으로는 분리하는 것이 좋습니다.

이유:

- API 응답 형식은 프론트 요구에 따라 자주 변합니다.
- domain 모델은 서비스 핵심 개념이라 더 안정적이어야 합니다.

---

## 9. Streamlit app.py는 어떻게 해야 하는가?

Streamlit은 버리는 것이 아니라, React Native 전 백엔드 검증용 클라이언트로 둡니다.

단, `app.py`가 현재처럼 비대해지면 안 됩니다.

권장 구조:

```text
frontend/streamlit_prototype/
│
├── app.py
├── api_client.py
├── state.py
└── components/
    ├── chat_panel.py
    ├── map_view.py
    ├── weather_card.py
    ├── route_summary.py
    ├── poi_overlay.py
    └── banner_carousel.py
```

`app.py`가 해야 할 일:

- page config
- session_state 초기화
- api_client 호출
- components 조립

`app.py`가 하지 말아야 할 일:

- 날씨 API 직접 호출
- DB 그래프 로드
- NetworkX 경로 계산
- GPT 프롬프트 처리
- 카카오맵 API 직접 호출
- custom_score 계산

이 원칙을 지키면 나중에 React Native로 전환할 때 백엔드는 그대로 두고 프론트만 교체할 수 있습니다.

---

## 10. 최종 데이터 흐름

### 앱 최초 진입

```text
Frontend
  -> POST /api/prewalk/init
     { user_id, lat, lon }

Backend application/prewalk
  -> weather_context 생성
  -> air_quality_context 생성
  -> 초기 추천 문구 생성
  -> UI events 생성

Frontend
  <- [
       { type: "text", payload: {...} },
       { type: "weather_card", payload: {...} }
     ]
```

### 사용자 채팅 후 경로 추천

```text
Frontend
  -> POST /api/prewalk/message
     { thread_id, message }

Agent
  -> intent 추출
  -> 필요한 context 조회
  -> route_tool 호출

Route Tool
  -> route_engine.route_orchestrator 호출

Route Engine
  -> graph_loader
  -> features
  -> profiles
  -> scoring_engine
  -> circular_engine / oneway_engine
  -> route_result_builder

Backend
  -> UI events 생성

Frontend
  <- [
       { type: "text", payload: {...} },
       { type: "map", payload: {...} },
       { type: "route_card", payload: {...} },
       { type: "poi_overlay", payload: {...} }
     ]
```

---

## 11. 팀 분업 기준

### Route Engine 팀

담당:

- `route_engine/features`
- `route_engine/profiles`
- `route_engine/scoring`
- `route_engine/engines`

목표:

- 기존 `path_*.py` 증식을 멈추고, feature/profile/engine 조합으로 통합합니다.

---

### Data/DB 팀

담당:

- `data/collectors`
- `data/migrations`
- `infrastructure/db`
- `infrastructure/repositories`

목표:

- 정적 Layer 1 데이터를 DB에 안정적으로 저장합니다.
- `safety_score`, `nature_score`, `slope_score`, `landmark_score` 등 feature를 일관된 방식으로 제공합니다.

---

### Agent/Application 팀

담당:

- `agent`
- `application`
- `context`
- `prompts`
- `memory`

목표:

- 사용자의 자연어 입력을 route profile/context/tool call로 변환합니다.
- 한 번의 추천 루프가 끝까지 자연스럽게 돌도록 만듭니다.

---

### Frontend/Prototype 팀

담당:

- `frontend/streamlit_prototype`
- 이후 `frontend/mobile_app`

목표:

- Streamlit은 백엔드 API 검증용 클라이언트로 유지합니다.
- 비즈니스 로직은 프론트에서 제거합니다.
- 백엔드가 주는 typed UI event를 렌더링합니다.

---

## 12. 리팩토링 진행 순서

### Phase 0: 문서와 계약 정리

- RouteRequest 정의
- RouteResult 정의
- FeatureSpec 정의
- Profile 정의
- UIEvent 정의

### Phase 1: Route Engine 3-Layer 정리

- `features/`
- `profiles/`
- `scoring/`
- `engines/`
- `route_orchestrator.py`

### Phase 2: DB/Feature Registry 정리

- 정적 Layer 1 feature 목록 확정
- 컬럼 vs JSONB 전략 결정
- graph_loader가 feature를 동적으로 로드하도록 설계

### Phase 3: Context + Live Layer 1.5

- 날씨
- 미세먼지
- 카카오맵 주변 POI
- 현재 위치 context

### Phase 4: Agent One Loop

- 초기 메시지
- 사용자 의도 분석
- route profile 선택
- route tool 호출
- UI event 응답

### Phase 5: Streamlit 얇게 만들기

- `app.py` 컴포넌트화
- API client 분리
- 백엔드 API만 호출하도록 정리

### Phase 6: React Native 전환

- 같은 API를 React Native에서 호출
- Streamlit은 내부 검증 도구로 유지

---

## 13. 이 문서의 핵심 메시지

Gemini와 논의한 3-Layer route architecture는 버리는 것이 아니라, 전체 시스템의 핵심 엔진으로 유지합니다.

다만 전체 앱 서비스를 만들기 위해서는 route engine 바깥에 다음 계층이 필요합니다.

```text
api          -> 프론트가 호출하는 HTTP 입구
application  -> 서비스 흐름 조립
agent        -> LLM 기반 판단 루프
domain       -> 핵심 모델
context      -> 현재 상황 정보
memory       -> 대화/취향/기록 저장
infrastructure -> DB, 외부 API, cache
schemas      -> API 요청/응답 DTO
```

최종 목표는 다음입니다.

```text
Streamlit app.py
  = 검증용 얇은 렌더러

React Native
  = 실제 앱 렌더러

FastAPI Backend
  = 실제 서비스 중심

Route Engine
  = 순수 경로 계산 코어

Agent/Application
  = 날씨, 의도, POI, 라우팅을 조립하는 판단 계층
```

