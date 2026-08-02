# 챗봇 Prewalk 대화 테스트 시나리오

> 상태: Current
> 기준일: 2026-08-02
> 관련 코드: `scripts/test_prewalk_conversation.py`, `src/agent/nodes/extractor.py`, `src/agent/nodes/interviewer.py`, `src/agent/nodes/confirmation_classifier.py`
> 검증 상태: 11개 시나리오 1차 실행 완료(2026-08-02, 로컬 PostgreSQL·Valkey + 실제 Kakao·OpenAI). 크래시 2건(7·9번), Extractor 기본값 오채움 2건(2·3번), 의도가 재현되지 않은 시나리오 2건(10·11번), RouteExecutor 이후 response 미갱신(4·5·6·10번), 상태와 불일치하는 응답 문구(11번) 발견

## 1. 목적과 범위

이 문서는 `scripts/test_prewalk_conversation.py`가 다뤄야 하는 대화 시나리오와 그 실행 결과를 함께 관리하는 단일 기준 문서다. 스크립트를 수정할 때는 먼저 이 문서의 시나리오 표를 갱신하고, 실행한 뒤에는 같은 표의 실행 결과 칸에 관측값을 기록한다.

- 이 스크립트는 로컬 PostgreSQL·Valkey와 실제 Kakao·OpenAI를 그대로 호출하는 수동 실행용이며, `tests/integration/test_api.py`처럼 mock Orchestrator로 자동 검증하는 것과는 성격이 다르다.
- `WeatherChecker`와 `RouteExecutor`(경로 엔진·profile 선택)는 이 문서의 범위가 아니다. 챗봇 대화 흐름(`Extractor`·`Interviewer`·`ConfirmationClassifier`)과 직결되는 부분만 다룬다.
- 모드 용어: `extraction.yaml` 기준으로 순환(`select_circular`), 편도(`select_oneway`, 목표 거리 포함), 편도 최단(`select_oneway_shortest`, 거리 무관 최단경로) 3종이다. `OnewayPreference` 스키마 docstring은 `select_oneway`를 "편도 우회 경로"라고도 부른다.
- agent_harness.md §9는 이 스크립트가 아닌 다른 방식(프런트엔드 연동 안드로이드 기기 등)으로 확인한 시스템 전체 검증 이력을 관리한다. 이 문서는 그 이력과 별개로 `scripts/test_prewalk_conversation.py` 실행 결과만 관리한다.

## 2. 시나리오와 실행 결과

| # | 카테고리 | 발화 | 검증 포인트 | 예상 결과 | 스크립트 반영 | 실행 결과 |
|---|---|---|---|---|---|---|
| 1 | 서비스 지역 밖 | "부산 해운대에서 3km 순환 산책하고 싶어" | 서울 도보망 밖 실존 지명 처리 | 불확실. `Interviewer._execute_tool_calls`의 tool-call 검색 경로는 `is_within_seoul_bbox`로 후보를 거르지만, place_name만 있고 좌표 없을 때의 자동 보완 경로(241~256행)는 이 필터가 없어 그대로 진행되다 `RouteExecutor`/그래프 단계에서 실패할 가능성 있음 | 반영됨 | 2026-08-02(로컬 PostgreSQL·Valkey + 실제 Kakao·OpenAI). origin이 좌표 없이 place_name="부산 해운대"로만 남고, Interviewer가 "해운대 해수욕장"처럼 더 구체적인 장소명을 요청. 에러 없이 재질문으로 처리됨. bbox 필터가 걸린 건지 Kakao 검색 자체가 결과 없이 끝난 건지는 로그로 구분 안 됨 |
| 2 | 무관한 발화(Extractor) | "오늘 뭐 먹지?" (첫 턴, 산책 정보 없음) | 산책과 무관한 첫 발화 처리 | mode·context 대부분 null로 남고 `Interviewer`가 모드·위치·거리 등 기본 정보를 묻는 질문 생성, `is_complete=False` | 반영됨 | 2026-08-02. 예상과 다름: mode/context가 비지 않고 Extractor가 `select_circular(target_km=3.0 기본값, origin=현재위치)`를 임의로 채워 곧바로 `awaiting_confirmation=True`로 진입. 근거 없는 기본 경로가 재질문 없이 확정 대기 상태로 넘어감(3번과 동일 패턴, 잠재 버그) |
| 3 | 무관한 발화(ConfirmationClassifier) | "여의도공원에서 2km 순환 코스로 산책할래" → "오늘 날씨 어때?" | 확인 대상과 무관한 응답이 부정으로 판정되는지 | 부정 판정 → `awaiting_confirmation=False`, `is_complete=False` → `Extractor` 재진입(기존 `user_context` 유지) | 반영됨 | 2026-08-02. 부정 판정과 재확인 질문 재생성 자체는 예상대로 동작. 다만 Extractor가 "오늘 날씨 어때?"에도 2번과 동일하게 `select_circular` 기본값을 다시 채워, 사용자 동의 없이 target_km이 2.0→3.0으로 바뀐 채 재확인 질문이 나감 |
| 4 | 모드-순환 | "여의도공원에서 2km 순환 코스로 산책하고 싶어" → "응" | `select_circular` 기본 흐름 | `select_circular` 추출 → "여의도공원에서 출발하는 2km 순환 산책이 맞나요?" 확인 질문 → 긍정 → `RouteExecutor` 진입, `route_result.status=success` | 반영됨 | 2026-08-02. 추출·확인질문·긍정 판정·RouteExecutor 진입까지 챗봇 로직은 예상대로 동작. RouteExecutor가 `WalkRouteStatus.NO_NEAREST_START_NODE`로 실패했으나 경로 엔진 이슈로 이 문서 범위 밖. 단, `route_executor.py`가 `state.response`를 갱신하지 않아 turn 2 이후에도 `response`가 turn 1의 확인 질문 문구 그대로 남음(성공·실패 무관, RouteExecutor를 거치는 모든 시나리오 공통) |
| 5 | 모드-편도 | "홍대에서 합정역까지 3km 정도 예쁜 골목길로 걷고 싶어" → "응" | `select_oneway`(target_km 포함) 기본 흐름 | `select_oneway`(target_km=3.0) 추출 → "홍대부터 합정역까지가 맞나요?" 확인 질문 → 긍정 → `RouteExecutor` 진입 | 반영됨 | 2026-08-02. 4번과 동일 패턴: select_oneway(target_km=3.0 포함) 추출·확인질문·긍정 판정은 예상대로 동작. RouteExecutor만 NO_NEAREST_START_NODE(범위 밖). `response`도 4번과 동일하게 turn 1 확인 질문 문구 그대로 남음 |
| 6 | 모드-편도 최단 | "구파발역에서 연신내역까지 최단 경로로 가고 싶어" → "응" | `select_oneway_shortest`(target_km 없음) 기본 흐름 | `select_oneway_shortest` 추출(target_km 없음) → "구파발역부터 연신내역까지가 맞나요?" 확인 질문 → 긍정 → `RouteExecutor` 진입 | 반영됨 | 2026-08-02. 4번과 동일 패턴: select_oneway_shortest(target_km 없음) 추출·확인질문·긍정 판정은 예상대로 동작. RouteExecutor만 NO_NEAREST_START_NODE(범위 밖). `response`도 4번과 동일하게 turn 1 확인 질문 문구 그대로 남음 |
| 7 | Interviewer-정보부족 | "3km 편도로 산책하고 싶어" (목적지 없음) | 목적지 누락 시 재질문 | `_missing_fields`에 "목적지 장소명 또는 좌표" 포함 → 목적지를 묻는 재질문, `is_complete=False` 유지 | 반영됨 | 2026-08-02. 예상과 다름(심각): 재질문 대신 크래시. Extractor가 select_oneway tool을 destination=None으로 호출해 Pydantic ValidationError → `status=INTERNAL_ERROR`. tool 호출 전에 목적지 누락을 막는 방어 로직이 없음 |
| 8 | Interviewer-검색실패 | "아리스토텔레스빌리지에서 걷고 싶어" (존재하지 않는 지명) | Kakao 검색 결과 0건일 때 반응 | `destination_candidate`가 채워지지 않아 목적지 정보 부족 상태로 재질문 예상. 정확한 안내 문구는 코드 근거가 약해 불확실 | 반영됨 | 2026-08-02. 예상과 다름: destination_candidate 미채움이 아니라 origin·destination이 모두 "아리스토텔레스빌리지"(좌표 없음)로 동일하게 채워졌고, Interviewer가 "출발지와 목적지가 동일하다"는 이유로 목적지를 재질문. 결과적으로 재질문은 나왔지만 실제 원인(존재하지 않는 지명)과 응답 근거(출발지=목적지)가 어긋남 |
| 9 | Interviewer-다른 경로 요청 | Interviewer가 후보/제안을 준 상태에서 "다른 경로로 해줄 수 있어?" | 확정 전 대체 요청에 대한 반응 | 전용 처리 로직이 코드에 안 보여 가장 불확실. 발화가 무시되거나 무관한 발화처럼 취급될 가능성 | 반영됨 | 2026-08-02. 7번과 동일한 크래시: 부정 판정 후 Extractor 재진입에서 select_oneway_shortest를 destination=None으로 호출해 ValidationError, `status=INTERNAL_ERROR`. "다른 경로 요청"에 대한 전용 반응은 크래시로 인해 확인하지 못함 |
| 10 | Interviewer-출발지=목적지 | "용산역에서 용산역으로 가는 길 알려줘" | origin=destination으로 동일하게 명시됐을 때 처리 방식 | 둘 다 location이 채워져 `_missing_fields`에 안 걸림 → "용산역부터 용산역까지가 맞나요?" 그대로 확인 질문 생성 → 긍정 시 `RouteExecutor`가 origin=destination을 어떻게 처리할지 불확실(0km·오류 가능성) | 반영됨 | 2026-08-02. 시나리오 의도가 재현되지 않음: Extractor가 origin의 "~에서"를 인식하지 못하고 origin을 현재 위치(서울시청)로 기본 설정, destination만 "용산역"으로 추출함. origin=destination 동일 명시 케이스는 확인하지 못함. 이후 확인질문·긍정·RouteExecutor(NO_NEAREST_START_NODE, 범위 밖)는 정상 흐름이며, `response`도 4번과 동일하게 turn 1 확인 질문 문구 그대로 남음 |
| 11 | ConfirmationClassifier-애매한 긍정 | "광화문역에서 인스타 감성 카페거리까지 가줘" → "그걸로 해줘" | 명시적 긍정 단어 없이도 긍정 판정되는지 | `confirmation.yaml`이 긍정으로 판정 → `is_complete=True` → `RouteExecutor` 진입 예상(agent_harness.md가 이미 미확인으로 남긴 항목이라 확신도는 중간) | 반영됨 | 2026-08-02. 시나리오 설계 결함: destination("인스타 감성 카페거리")이 Kakao에서 해결되지 않아 turn 1 이후에도 `awaiting_confirmation=False`로 남음. turn 2 "그걸로 해줘"가 ConfirmationClassifier를 거치지 않고 동일한 위치 보완 요청으로 재처리됨. 애매한 긍정 판정 자체는 검증하지 못함. 추가로, turn 2의 `context`는 turn 1과 완전히 동일(destination 여전히 좌표 없음, `awaiting_confirmation=False`, `is_complete=False`, `route_result` 없음)한데도 `response`는 "알겠습니다! ... 산책 코스를 준비할게요"라며 마치 진행되는 것처럼 답해 실제 상태와 응답 문구가 어긋남(`interview.yaml` 2차 자유 생성 호출이 원인으로 추정) — 실제 검색되는 destination으로 재작성 필요 |

인증·세션·소유권 실패(만료 토큰, 없는 thread, 타 사용자 thread)와 Valkey TTL 만료는 이미 격리 환경에서 별도로 확인된 적이 있어([챗봇 경로 추천 Workflow](../architecture/workflows/prewalk_conversation.md) §6) 이 문서의 대상에 포함하지 않는다.

### 2026-08-02 1차 실행에서 발견한 문제

- **크래시(7, 9번)**: 목적지 없이 편도/편도 최단 요청이 Extractor에 들어가면 `select_oneway`/`select_oneway_shortest` tool이 `destination=None`으로 호출돼 Pydantic `ValidationError`로 대화가 끊긴다(`status=INTERNAL_ERROR`). 두 시나리오 모두 원래 검증하려던 내용(재질문, 대체 요청 반응)을 확인하지 못했다.
- **Extractor가 무관한 발화에도 기본값을 채움(2, 3번)**: "오늘 뭐 먹지?"·"오늘 날씨 어때?"처럼 산책과 무관한 발화에도 `select_circular(target_km=3.0 기본값, origin=현재위치)`가 채워지며, 재질문 없이 확인 대기 상태로 진행되거나 기존 `target_km`이 사용자 동의 없이 바뀐다.
- **시나리오가 의도한 상황을 재현하지 못함(10, 11번)**: 10번은 origin의 "~에서" 표현이 무시돼 origin=destination 동일 명시 케이스가 재현되지 않았고, 11번은 destination이 Kakao에서 해결되지 않아 확인 대기 상태 자체에 도달하지 못해 애매한 긍정 판정이 검증되지 않았다.
- 4, 5, 6, 10번의 `RouteExecutor` 단계 `NO_NEAREST_START_NODE` 실패는 경로 엔진 이슈로 이 문서 범위 밖이며, 챗봇 쪽(추출·확인질문·판정) 로직 자체는 이 네 시나리오에서 예상대로 동작했다.
- **RouteExecutor 이후 response 미갱신(4, 5, 6, 10번)**: `route_executor.py`는 `state.route_result`와 `state.profile`만 쓰고 `state.response`는 성공·실패와 무관하게 전혀 갱신하지 않는다. 그 결과 확인 질문에 긍정해 `RouteExecutor`가 실행된 뒤에도 사용자에게 보이는 `response`는 turn 1의 확인 질문 문구 그대로 남는다.
- **상태와 어긋나는 응답 문구(11번)**: turn 2 "그걸로 해줘" 처리 후 `context`(destination 좌표 없음)·`awaiting_confirmation`·`is_complete`·`route_result` 모두 turn 1과 동일해 실질적으로 아무 진행이 없었는데도, `response`는 "산책 코스를 준비할게요"라며 진행되는 것처럼 답한다. `Interviewer`의 2차 자유 생성 호출(`interview.yaml`, tool 미바인딩)이 실제 필드 상태를 반영하지 않고 문구를 만들어내는 것이 원인으로 추정된다.

## 3. 관리 원칙

- 스크립트의 `SCENARIOS`를 추가·삭제·수정하면 같은 작업에서 위 표의 "스크립트 반영" 칸도 갱신한다.
- 시나리오를 실행하면 "실행 결과" 칸에 확인 날짜·환경(로컬/격리, 사용한 DB·외부 API)과 관측값(판정 결과, 오류 메시지 등)을 기록하고, "예상 결과"와 다르면 그 차이를 함께 적는다. 일회성 관측값은 고정 기대값처럼 쓰지 않는다.
- "예상 결과"가 코드 근거 없이 추측이었던 항목은 실행 후 실제 근거로 대체한다. 크래시로 검증 자체가 안 된 항목(현재 7, 9번)과 의도한 상황이 재현되지 않은 항목(현재 10, 11번)은 "예상 결과"를 그대로 두고 재작성·재실행 후 갱신한다.
- 새 시나리오를 추가하면 번호를 이어서 붙이고 "스크립트 반영"은 "미반영", "실행 결과"는 "미실행"으로 시작한다.

## 4. 완료 기준

- 표의 번호·카테고리·발화가 `scripts/test_prewalk_conversation.py`의 `SCENARIOS`와 정확히 일치한다(반영됨으로 표시된 항목 기준).
- 모든 "반영됨" 시나리오에 확인 날짜가 있는 실행 결과가 있고, 예상 결과와 실제 결과의 일치 여부가 기록돼 있다.
- 미반영 시나리오는 왜 아직 다루지 않았는지 검증 포인트만으로 판단 가능하다.
