# 챗봇 경로 추천 Workflow

> 상태: Current  
> 기준일: 2026-07-27  
> 관련 코드: `src/interfaces/api/prewalk_router.py`, `src/service/chat/prewalk_service.py`, `src/agent/`, `src/schema/prewalk_schema.py`  
> 검증 상태: 코드 추적 완료·OpenAI/Kakao/DB/Valkey/경로 통합 확인

## 1. 목적과 시작 조건

대화를 통해 경로 모드·출발지·목적지·거리·테마를 수집하고, 사용자 확인 후 직접 경로 엔진을 실행하는 흐름이다.

- `POST /api/prewalk/init`: access cookie와 현재 좌표로 세션·초기 State 생성
- `POST /api/prewalk/intent`: `thread_id`와 사용자 발화로 State 진행
- 시작 전 인증 사용자, PostgreSQL, Valkey, 메모리 Graph가 필요하다.
- 초기 인사와 정보 추출에는 OpenAI, 날씨·주소·장소 검색에는 외부 API를 사용한다.

## 2. 참여 코드

| 코드 | 역할 |
|---|---|
| `prewalk_router.py` | init 좌표 검증과 두 API 계약 |
| `PrewalkOrchestrator` | 인증·소유권·State 저장과 LangGraph 분기 |
| `State`, `ChatSession`, `ChatStateRepository` | 대화 상태 계약과 PostgreSQL/Valkey 저장 |
| `WeatherChecker` | 날씨·대기질 기반 LLM 첫 인사 |
| `Extractor` | LLM tool call로 모드·위치·거리·테마 추출 |
| `Interviewer` | 누락 질문·Kakao 장소 검색·최종 확인 |
| `RouteExecutor`, `RouteTool` | 설문·테마 가중치 조합과 `RouteService` 실행 |

## 3. 정상 흐름

```text
init: 좌표 schema·서울 Polygon·수계·보행 가능 검증
→ JWT 사용자 확인 → PostgreSQL ChatSession(START) 생성
→ 날씨·대기질 → OpenAI 초기 인사
→ Kakao 주소 → 초기 State
→ Valkey chat_state:{thread_id}(TTL 1시간) 저장

intent: JWT 확인 → Valkey State 조회 → State.user_id 소유권 확인
→ Extractor → Interviewer
→ 정보 부족: 질문 후 State 저장
→ 정보 충분: awaiting_confirmation=true로 확인 질문 후 저장
→ 긍정 응답: RouteExecutor 직접 실행 → RouteService → RouteHistory
→ 최종 State 저장·반환
```

부정 응답은 LangGraph를 실행하지 않고 확인 대기를 해제한 뒤 변경할 항목을 다시 묻는다. 다음 턴은 기존 `user_context`를 유지해 일부만 수정한다.

## 4. 상태 변화와 결과

- PostgreSQL `chat_sessions`에는 사용자·UUID thread·`START`가 저장된다.
- 전체 `State`는 Valkey에 JSON으로 저장되며 intent마다 TTL이 3,600초로 갱신된다.
- State는 현재 위치, 날씨, 모드별 preference, 후보 위치, 테마, 확인 상태와 경로 결과를 가진다.
- intent 처리 때 State에 access JWT를 넣으며 현재 API 응답과 Valkey JSON에도 포함된다.
- 경로 성공 시 `RouteService`가 `route_histories`를 저장하고 State의 `route_result.id`에 연결한다.
- 현재 구현은 대화·경로 완료 후에도 PostgreSQL `ChatSession.current_state`를 `START`에서 변경하지 않는다.

## 5. 실패·복구

| 조건 | 현재 결과 | 복구 |
|---|---|---|
| 좌표 schema 오류 | HTTP 422 | 입력 수정 |
| 서울 Polygon·보행 불가 좌표 | HTTP 400 | 위치 수정 |
| token 없음·손상 | HTTP 200 / 인증 상태 | refresh 또는 재로그인 |
| Valkey State 없음·TTL 만료 | `session_not_found` | init부터 재시작 |
| 다른 사용자의 thread | `unaccessible` | 자신의 thread 사용 |
| DB·Valkey load 또는 Node 예외 | `internal_error` | 의존성 복구 후 해당 단계 재시도 |
| 초기 날씨·주소 실패 | 기본 인사·좌표 Location으로 계속 | 외부 API 복구 후 새 init |
| State 저장 실패 | 성공 응답은 반환하지만 다음 intent에서 세션 유실 가능 | Valkey 복구 후 init 재시작 |

Node 내부의 일부 LLM·경로 실패는 예외 대신 기존 State를 반환한다. HTTP 200만으로 완료를 판단하지 말고 `awaiting_confirmation`, `is_complete`, `route_result.status`를 확인한다.

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

공공데이터가 실패해 빈 날씨·대기질이 전달됐지만 LLM 인사는 날씨와 대기질이 좋다고 표현했다. 결측 입력에 대한 프롬프트 계약이 없어 사실과 다른 안내가 생성될 수 있다.

한글 확인 응답은 실행 셸 인코딩 영향 때문에 증거에서 제외하고 코드가 지원하는 `yes`로 긍정 분기를 확인했다. 편도 모드, 장소 후보 선택, State 저장 장애와 TTL 실제 만료는 아직 실행하지 않았다.
