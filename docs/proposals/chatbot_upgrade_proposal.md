# 챗봇 Agent 업그레이드 제안

> 상태: Proposal  
> 기준일: 2026-07-27  
> 기준 문서: [현재 챗봇 Agent 하네스](../chatbot/agent_harness.md)  
> 대상 코드: `src/agent/`, `src/service/chat/prewalk_service.py`, `src/schema/prewalk_schema.py`

## 1. 목적과 범위

현재 챗봇을 한 번에 재작성하지 않고, 사람이나 AI가 독립 작업 단위로 나눠 변경하고 각 결과를 안전하게 연결·검증할 수 있는 업그레이드 순서를 제안한다.

이 문서는 아직 구현되지 않은 선택지와 완료 조건을 다룬다. 현재 동작의 기준은 `agent_harness.md`, 실제 API 흐름과 실행 증거는 [챗봇 경로 추천 Workflow](../architecture/workflows/prewalk_conversation.md)를 따른다.

범위:

- State의 저장·응답·보안 경계
- Node·Edge와 사용자 확인 흐름
- ChatSession 생명주기
- 외부 데이터 결측과 Node 실패 계약
- Prompt·Tool·Graph 자동 검증

제외:

- `frontend/**`
- 경로 엔진 알고리즘 자체의 재설계
- 이 문서만으로 승인되지 않은 코드 변경

## 2. 현재 코드에서 확인된 개선 대상

| ID | 현재 사실 | 위험·비용 |
|---|---|---|
| C1 | Graph에 `Interviewer → RouteExecutor` 조건부 Edge가 있지만 현재 실행에서는 도달하지 않는다. 긍정 확인 턴은 Orchestrator가 직접 실행한다. | 흐름을 수정할 때 Graph 선언만 보고 잘못 연결할 수 있다. |
| C2 | intent에서 access JWT를 State에 넣고 전체 State를 Valkey와 API 응답에 전달한다. | 대화 상태와 인증 비밀의 수명·노출 범위가 결합된다. |
| C3 | `ChatSession.current_state`는 생성 때 `START`가 되고 이후 변경되지 않는다. | 활성·완료 세션 조회와 운영 판단이 실제 대화 상태를 나타내지 못한다. |
| C4 | 공공데이터 결측 상태에서도 LLM 초기 인사가 날씨·대기질이 좋다고 표현한 실행 사례가 있다. | 결측을 사실처럼 보완하는 응답이 생길 수 있다. |
| C5 | 일부 Node는 실패를 예외로 전달하지 않고 기존 State를 반환한다. | HTTP 성공과 실제 경로 생성 성공을 구분하기 어렵다. |
| C6 | Valkey 저장 실패 뒤에도 성공 응답이 반환될 수 있다. | 현재 응답은 성공하지만 다음 턴에서 세션이 유실될 수 있다. |
| C7 | 실제 Node·Edge·State 저장·LLM Tool 호출을 검증하는 자동 테스트가 없다. | 업그레이드 전후의 행동 차이를 자동으로 판정할 기준이 없다. |
| C8 | `complete.yaml`, `route_result.yaml`과 관련 호출 주석이 남아 있다. | 사용 중인 Prompt 경계가 불명확하다. |

## 3. 먼저 승인할 설계 결정

구현 전에 아래 결정을 기록한다. 서로 다른 작업자가 각자 가정해 구현하지 않도록 한 항목당 하나의 선택지만 승인한다.

| 결정 | 선택지 A | 선택지 B | 승인 기준 |
|---|---|---|---|
| D1 확인 흐름 | 확인과 긍정 처리를 Graph 안의 명시적 Node·Edge로 통합 | 확인은 Orchestrator에 유지하고 도달 불가 Edge 제거 | 실제 진입점이 하나이며 다중 턴 테스트로 추적 가능 |
| D2 State 경계 | 내부 State, 캐시 State, API 응답 schema 분리 | 단일 State를 유지하되 저장·응답 제외 필드 지정 | JWT가 Valkey와 응답에 포함되지 않음 |
| D3 세션 상태 | `START → COLLECTING → CONFIRMING → COMPLETED/FAILED` | 최소 `START → COMPLETED` | 각 상태의 작성 주체·전이·재시도 규칙이 명확 |
| D4 실패 표현 | Node 결과에 명시적 오류 상태 추가 | 예외를 Orchestrator까지 전달해 `ChatStatus`로 변환 | 경로 없음과 경로 성공을 응답에서 구분 가능 |
| D5 저장 실패 | State 저장 성공 후 응답 | 응답하되 복구 가능한 별도 실패 상태 기록 | 성공 응답 뒤 다음 턴 유실을 탐지·복구 가능 |
| D6 LLM 검증 | 고정 응답·Tool call fixture 중심 | 실제 모델을 사용하는 제한적 평가 병행 | CI 안정성과 실제 모델 품질 확인을 분리 |

## 4. 독립 작업 단위

각 작업은 입력·출력·검증·복구가 독립적이어야 한다. 선행 작업의 완료 기준을 통과하기 전에는 다음 작업을 병합하지 않는다.

### P1. 현재 행동 특성화

- 책임: 업그레이드 전 현재 동작을 회귀 테스트로 고정한다.
- 입력: `agent_harness.md`, `prewalk_conversation.md`, 현재 API와 State schema
- 출력: init, 정보 부족, 확인 대기, 긍정, 부정, 만료, 타 사용자 흐름의 자동 테스트
- 의존성: 격리 PostgreSQL·Valkey, mock 외부 API
- 실패 복구: 제품 코드를 바꾸지 않고 fixture와 기대값만 재검토한다.
- 완료 기준: 선언 Edge와 실제 우회 흐름, State 저장 결과를 테스트가 구분한다.

### P2. 인증 정보와 State 분리

- 책임: Route 호출에 필요한 인증을 전달하되 대화 State·Valkey·API 응답에서 JWT를 제거한다.
- 입력: 승인된 D2, `State`, `ChatResponse`, `RouteExecutor`, `RouteTool`
- 출력: 인증 전달 계약과 마이그레이션 가능한 캐시 schema
- 의존성: P1
- 변경 영향: 기존 Valkey JSON, Node 호출 서명, API 응답
- 실패 복구: 구·신 캐시 형식을 읽는 임시 호환 계층 또는 세션 재초기화
- 완료 기준: 정상 경로 생성은 유지되고 저장 JSON·API 응답에 JWT가 없다.

### P3. ChatSession 생명주기 연결

- 책임: 대화 진행과 PostgreSQL 세션 상태를 일치시킨다.
- 입력: 승인된 D3, 확인 상태, 경로 성공·실패 결과
- 출력: 상태 전이 함수와 저장 책임자
- 의존성: P1
- 변경 영향: 활성 thread 조회, 재시작·완료 판단
- 실패 복구: 전이 실패 시 마지막 유효 상태와 재시도 시작점 기록
- 완료 기준: 정상·부정·실패 흐름별 전이가 테스트되고 완료 세션이 활성 조회에서 제외된다.

### P4. 확인 흐름 단일화

- 책임: 선언 Graph와 실제 실행 경로를 하나의 계약으로 만든다.
- 입력: 승인된 D1, P1 특성화 테스트
- 출력: 도달 가능한 Node·Edge 또는 명시적인 Orchestrator 흐름
- 의존성: P1, 필요하면 P3
- 변경 영향: `awaiting_confirmation`, `is_complete`, 긍정·부정 판정
- 실패 복구: 기존 흐름을 feature flag 또는 단일 커밋 revert로 복원
- 완료 기준: 모든 선언 Edge의 도달성 테스트와 긍정·부정 다중 턴 테스트가 통과한다.

### P5. 외부 데이터 결측 계약

- 책임: 날씨·대기질·주소 결측을 LLM이 사실로 보완하지 않게 한다.
- 입력: `EnvironmentInfo`, `weather_checker.yaml`, 외부 API 실패 형태
- 출력: 결측 표시 규칙, 기본 응답, Prompt fixture
- 의존성: P1
- 변경 영향: 초기 인사 문구와 외부 API fallback
- 실패 복구: LLM을 호출하지 않는 기존 기본 인사로 전환
- 완료 기준: 전체·부분 결측 fixture에서 확인되지 않은 날씨를 단정하지 않는다.

### P6. Node 실패와 저장 실패 명시화

- 책임: 경로 생성 실패와 State 저장 실패를 호출자가 판정하게 한다.
- 입력: 승인된 D4·D5, 각 Node의 예외 처리
- 출력: 오류 상태 또는 예외·응답 변환 계약
- 의존성: P1, P2
- 변경 영향: `ChatStatus`, `route_result`, 재시도 위치, 로그
- 실패 복구: 마지막 저장 State에서 멱등 재시도하거나 init부터 재시작
- 완료 기준: LLM·Kakao·RouteService·Valkey 장애별 응답과 복구 시작점이 테스트된다.

### P7. Prompt·Tool·Graph 검증과 잔재 정리

- 책임: 실제 사용 Prompt·Tool 목록을 자동 확인하고 미사용 파일 처리 근거를 남긴다.
- 입력: P1–P6 결과, `src/prompt/`, Tool map, Graph
- 출력: Prompt 렌더링·Tool 인자·Edge 도달성 테스트와 사용 목록
- 의존성: P4–P6
- 변경 영향: Prompt 이름, parser, Tool schema
- 실패 복구: Prompt·Tool 변경을 독립 커밋으로 되돌린다.
- 완료 기준: 사용 목록과 코드가 일치하고 삭제·보존 결정이 문서화된다.

## 5. 권장 연결 순서

```text
P1 현재 행동 특성화
├─ P2 인증 정보와 State 분리
├─ P3 세션 생명주기
└─ P5 외부 데이터 결측 계약
      ↓
P4 확인 흐름 단일화
      ↓
P6 실패 계약 명시화
      ↓
P7 Prompt·Tool·Graph 검증과 잔재 정리
```

P1은 모든 변경의 비교 기준이다. P2·P3·P5는 계약 충돌이 없도록 각각 독립 브랜치나 독립 커밋으로 수행할 수 있다. P4 이후에는 Graph 실행 계약이 달라지므로 P6·P7이 새 흐름을 기준으로 이어받는다.

## 6. 공통 검증 게이트

각 작업은 다음 증거를 남긴다.

1. 변경 전 실패 또는 현재 행동을 보여주는 테스트
2. 변경 후 단위 테스트와 API 통합 테스트
3. 저장된 PostgreSQL 행과 Valkey JSON 확인
4. 정상·결측·외부 장애·재시도 결과
5. State·Node·Edge·Tool 계약 변경에 따른 Current 문서 갱신
6. 되돌릴 파일·데이터와 복구 명령

실제 OpenAI 호출 평가는 결정적 CI 테스트와 분리하고, 사용 모델·Prompt 버전·실행일·입력 fixture를 함께 기록한다.

## 7. Proposal 승인과 완료 기준

구현 시작 전:

- D1–D6의 선택과 근거를 팀이 승인한다.
- P1의 테스트 범위와 격리 실행 환경을 확정한다.
- 각 작업의 담당자, 선행 의존성, 결과 인계 문서를 정한다.

업그레이드 완료:

- `agent_harness.md`가 새 코드와 다시 대조된다.
- `prewalk_conversation.md`의 정상·실패·복구 결과를 재실행한다.
- JWT 저장·응답 제외, 세션 전이, 확인 흐름, 결측 응답, 장애 복구를 자동 검증한다.
- 승인되지 않은 Proposal 문장을 Current 문서에 남기지 않는다.
