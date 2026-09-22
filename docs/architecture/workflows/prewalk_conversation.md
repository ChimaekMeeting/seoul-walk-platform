# 챗봇 경로 추천 Workflow

> 상태: Current  
> 기준일: 2026-07-30
> 관련 코드: `src/interfaces/api/prewalk_router.py`, `src/service/chat/prewalk_service.py`, `src/agent/`, `src/schema/prewalk_schema.py`  
> 검증 상태: 프로필 전달 단위 테스트 완료·기존 OpenAI/Kakao/DB/Valkey/경로 통합 확인  
> 2026-09-23 `oneway_shortest`(편도 최단)는 `Interviewer`가 확인 질문 전에 최종 경로를 미리 계산해 `State.route_result`에 채워두고, 사용자가 긍정 확인하면 `RouteExecutor`는 그 값을 재계산 없이 그대로 반환한다. 노드별 계약·근거·단위 테스트는 [챗봇 Agent 하네스](../../chatbot/agent_harness.md)의 "2026-09-23 후속2"를 단일 기준으로 참고한다 — 이 문서는 여기서 세부를 반복하지 않는다.  
> 2026-09-24 `ConfirmationClassifier` Node(확인 응답 긍정/부정 LLM 판정)를 삭제했다. FE가 확인 질문에 버튼으로 답하고 그 값을 `ChatRequest`의 새 필드 `confirmation`(`Optional[bool]`)으로 따로 보내면서(`user_prompt`는 "아니요"의 교정 내용 전용으로 분리), `PrewalkOrchestrator.orchestrator()`가 그 값을 그대로 반영해 직접 판정한다(그래프 진입점도 `awaiting_confirmation` 대신 이 판정 결과인 `is_complete`를 본다). 근거·단위 테스트는 [챗봇 Agent 하네스](../../chatbot/agent_harness.md)의 "2026-09-24"를 참고한다.  
> 2026-09-25 확인을 받아 `RouteExecutor`가 경로 생성을 호출하는 바로 그 턴(`is_complete=True`)에는 GPS 좌표가 바뀌어도 `current_location`을 갱신하지 않는다(PostGIS 검증·Kakao 역지오코딩 스킵). 그 이후에 오는 `user_prompt`는 무언가 수정할 게 있어서 오는 새 요청으로 보고(그때는 `is_complete`가 다시 `False`) 현위치 갱신을 재개한다 — "확인 후 영원히 멈춤"이 아니라 "경로 생성을 부르는 그 턴만" 스킵한다. 새 필드 추가 없이 기존 `is_complete`를 재사용한다. 근거·단위 테스트는 [챗봇 Agent 하네스](../../chatbot/agent_harness.md)의 "2026-09-25"를 참고한다.  
> 2026-09-25 후속 `POST /api/prewalk/intent`가 JSON 한 번 응답에서 SSE(`text/event-stream`)로 바뀌었다 — Node가 하나 끝날 때마다 `event: progress`(텍스트), 그래프가 끝나면 `event: result`(JSON `ChatResponse`), 처리 중 실패하면 `event: error`(텍스트)를 내려보낸다. `PrewalkOrchestrator.orchestrator()`는 `graph.astream(stream_mode="updates")`를 쓰는 async generator로 바뀌었고, 스트리밍 시작 뒤에는 HTTP status를 못 바꿔 `/intent`의 실패도 HTTP 4xx/5xx 대신 `event: error`로 알린다(`/init`은 영향 없음, 아래 "5. 실패·복구" 참고). 근거·단위 테스트는 [챗봇 Agent 하네스](../../chatbot/agent_harness.md)의 "2026-09-25 후속"을 참고한다.

## 1. 목적과 시작 조건

대화를 통해 경로 모드·출발지·목적지·거리·테마를 수집하고, 사용자 확인 후 직접 경로 엔진을 실행하는 흐름이다.

- `POST /api/prewalk/init`: access cookie와 현재 좌표로 세션·초기 State 생성
- `POST /api/prewalk/intent`: `thread_id`와 사용자 발화로 State 진행. 응답은 SSE(`text/event-stream`, 2026-09-25 후속)다
- 시작 전 인증 사용자, PostgreSQL, Valkey, 메모리 Graph가 필요하다.
- 정보 추출에는 OpenAI, 주소·장소 검색에는 외부 API를 사용한다. 초기 인사는 2026-09-21부터 LLM·외부 API 호출 없는 고정 문구다.

## 2. 참여 코드

| 코드 | 역할 |
|---|---|
| `prewalk_router.py` | init 좌표 검증과 두 API 계약 |
| `PrewalkOrchestrator` | 인증·소유권·State 저장과 LangGraph 분기 |
| `State`, `ChatSession`, `ChatStateRepository` | 대화 상태 계약과 PostgreSQL/Valkey 저장 |
| `Extractor` | LLM tool call로 모드·위치·거리·테마 추출 |
| `Interviewer` | 누락 질문·Kakao 장소 검색·최종 확인·편도 우회 최단거리 초과 안내(2026-09-21)·oneway_shortest 최종 경로 선계산(2026-09-23, `RouteTool` 재사용) |
| `RouteExecutor`, `RouteTool` | 설문·테마 가중치 조합과 `RouteService` 실행(oneway_shortest는 `Interviewer`가 이미 채워둔 `route_result`가 있으면 재실행 생략, 2026-09-23) |

## 3. 정상 흐름

```text
init: 좌표 schema·서울 Polygon·수계·보행 가능 검증
→ JWT 사용자 확인 → PostgreSQL ChatSession(START) 생성
→ 고정 문구 초기 인사(2026-09-21부터 LLM·외부 API 미호출)
→ Kakao 주소 → 초기 State
→ Valkey chat_state:{thread_id}(TTL 1시간) 저장

intent: JWT 확인 → Valkey State 조회 → State.user_id 소유권 확인
→ awaiting_confirmation=true였다면: ChatRequest.confirmation(bool)을 그대로
  긍정/부정으로 반영(Orchestrator, 2026-09-24 — FE가 확인 질문에 버튼으로 답하고
  그 값을 confirmation 필드로 따로 보낸다. user_prompt는 "아니요"에 곁들이는
  교정 내용 전용) → is_complete에 반영, awaiting_confirmation 해제
→ 긍정(is_complete=true): Extractor/Interviewer를 다시 거치지 않고 바로 RouteExecutor로
   (oneway_shortest면 Interviewer가 직전 턴에 이미 RouteTool로 최종 경로까지
    계산해 route_result에 채워둔 값을 그대로 반환, 2026-09-23)
   그 외 모드는 RouteExecutor가 테마·명시값으로 profile 선택
→ 부정 또는 새 정보 수집 턴(is_complete=false): Extractor → Interviewer
  → 정보 부족: 질문 후 State 저장
  → 정보 충분: awaiting_confirmation=true로 확인 질문 후 저장
    (oneway_shortest는 이 시점에 Interviewer가 이미 RouteTool로 최종 경로까지
     계산해 route_result에 채워둔다, 2026-09-23)
→ 설문 가중치와 테마 delta 결합 → RouteService → 주변 POI·RouteHistory
→ 최종 State 저장·반환
```

확인 대기 중 `confirmation=false`(또는 아예 안 옴)은 부정으로 처리돼 `Extractor`부터 다시 거친다 — 기존 `user_context`는 유지되므로, FE가 `user_prompt`에 교정 내용을 같이 실으면 그걸로 일부만 수정되고, 비어 있으면(버튼만 클릭) `Extractor`가 아무것도 새로 추출하지 못해 사실상 같은 확인 질문이 다시 만들어진다.

## 4. 상태 변화와 결과

- PostgreSQL `chat_sessions`에는 사용자·UUID thread·`START`가 저장된다.
- 전체 `State`는 Valkey에 JSON으로 저장되며 intent마다 TTL이 3,600초로 갱신된다.
- State는 현재 위치, 모드별 preference, 후보 위치, 테마, 확인 상태, 참고용 최단거리(`shortest_km`, `oneway_shortest`/`oneway_random`에서 `Interviewer`가 채움, 2026-09-23)와 경로 결과를 가진다.
- `route_result`는 `oneway_shortest`에서만 확인 질문 단계(`Interviewer`)부터 채워지고, 그 외 모드(`oneway_random` 포함)는 긍정 확인 후 `RouteExecutor` 단계부터 채워진다(2026-09-23) — `oneway_random`의 물리적 최단거리 계산은 목표 거리 비교용 참고 숫자(`shortest_km`)만 남기고 좌표는 들고 다니지 않는다(최종 경로는 GRASP+ALNS가 따로 만들어 `RouteExecutor`가 항상 덮어쓰므로). `prewalk_service.py::orchestrator`는 더 이상 매 턴 이 필드를 초기화하지 않고, `Interviewer`(oneway_shortest는 채움, 그 외는 명시적으로 `None`)와 `RouteExecutor`가 각자 실행될 때마다 명시적으로 채우거나 지운다.
- intent 처리 때 State에 access JWT를 넣으며 현재 API 응답과 Valkey JSON에도 포함된다.
- 경로 성공 시 `RouteService`가 `route_histories`를 저장하고 State의 `route_result.id`에 연결한다. `oneway_shortest`는 이 저장이 확인 질문 단계(`Interviewer`)에서 먼저 일어날 수 있다 — 순환/편도 우회가 후보 경로를 전부 저장해 두는 기존 방식과 같은 이유로, 사용자가 확인하지 않고 다른 요청으로 넘어가도 그 행은 그냥 안 쓰인다.
- 이동 편의 테마(`유모차`, `계단이 불편한`)는 내부 `accessible`, 편의 테마
  (`활기찬`, `힙한`)는 `convenient` 프로필로 전달된다. 사용자에게는
  `accessible`을 `이동이 편한 길`로 안내하며, State에 명시한 profile이 있으면
  그 값을 우선한다.
- 성공 경로에는 50m 안의 도보망 연결 POI가 `nearby_pois`로 포함된다.
- 현재 구현은 대화·경로 완료 후에도 PostgreSQL `ChatSession.current_state`를 `START`에서 변경하지 않는다.

## 5. 실패·복구

| 조건 | 현재 결과 | 복구 |
|---|---|---|
| 좌표 schema 오류 | HTTP 422(두 엔드포인트 공통 — 스트림 시작 전 요청 검증 단계) | 입력 수정 |
| 서울 Polygon·보행 불가 좌표(`init`) | HTTP 400 | 위치 수정 |
| 서울 Polygon·보행 불가 좌표(`intent`, 좌표가 바뀐 턴만, 2026-09-25 후속) | HTTP 200 + `event: error`(텍스트) — 스트리밍 시작 뒤엔 HTTP status를 못 바꾼다 | 위치 수정 |
| token 없음·손상 | HTTP 200 / 인증 상태 | refresh 또는 재로그인 |
| Valkey State 없음·TTL 만료 | `session_not_found` | init부터 재시작 |
| 다른 사용자의 thread | `unaccessible` | 자신의 thread 사용 |
| DB·Valkey load 또는 Node 예외 | `internal_error` | 의존성 복구 후 해당 단계 재시도 |
| 초기 주소(Kakao) 실패 | 좌표 Location으로 계속 | 외부 API 복구 후 새 init |
| State 저장 실패 | 성공 응답은 반환하지만 다음 intent에서 세션 유실 가능 | Valkey 복구 후 init 재시작 |

Node 내부의 일부 LLM·경로 실패는 예외 대신 기존 State를 반환한다. HTTP 200만으로 완료를 판단하지 말고 `awaiting_confirmation`, `is_complete`, `route_result.status`를 확인한다. `intent`는 2026-09-25 후속부터 이 판단을 SSE의 마지막 `event: result` payload(또는 실패 시 `event: error`)에서 해야 한다 — HTTP status는 성공·실패 관계없이 거의 항상 200이다.

## 6. 검증 결과

2026-07-27 격리 PostgreSQL·Valkey와 실제 Kakao·OpenAI를 사용해 서울시청 좌표에서 확인했다.

| 검증 | 결과 |
|---|---|
| init | HTTP 200 / `success`, UUID thread 생성 |
| 저장 | ChatSession 1건 `START`, Valkey TTL 3,600초 |
| 외부 | Kakao 주소와 OpenAI 성공, 공공데이터 403 |
| token 없음 | `access_expired_token` |
| 없는 thread | `session_not_found` |
| 타 사용자 thread | `unaccessible` |
| 정보 추출 | 순환 모드·거리 추출 후 확인 대기 |
| 긍정 확인 | HTTP 200, 경로 `success`, 61좌표·3.10km·이력 ID 4 |

(2026-07-27 당시 기록, 현재는 무의미함) 공공데이터가 실패해 빈 날씨·대기질이 전달됐지만 LLM 인사는 날씨와 대기질이 좋다고 표현했다 — 2026-09-21 `WeatherChecker` 제거로 초기 인사가 LLM 호출 없는 고정 문구가 되면서 이 문제 자체가 사라졌다.

한글 확인 응답은 실행 셸 인코딩 영향 때문에 증거에서 제외하고 코드가 지원하는 `yes`로 긍정 분기를 확인했다. 편도 모드, 장소 후보 선택, State 저장 장애와 TTL 실제 만료는 아직 실행하지 않았다.
