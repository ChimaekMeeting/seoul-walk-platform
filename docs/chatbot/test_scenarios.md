# 챗봇 Prewalk 대화 테스트 시나리오

> 상태: Current
> 기준일: 2026-08-03
> 관련 코드: `scripts/test_prewalk_conversation.py`, `src/agent/nodes/extractor.py`, `src/agent/nodes/interviewer.py`, `src/agent/nodes/confirmation_classifier.py`, `src/schema/prewalk_schema.py`
> 검증 상태: 7차 실행(2026-08-03)까지 완료. **11개 시나리오 전부 확정.** 1번(의정부역)에서 `out_of_seoul` 경로가 정상 동작함을 확인했고, 6차 실행에서 발견한 문구 버그(circular 모드인데 "도착하고 싶으신 곳" 언급)를 `interviewer.py`에서 수정한 뒤 7차 실행으로 재확인 완료. **알려진 미해결 UX 이슈(3번)**: 확인 대기 중 무관한 발화("오늘 날씨 어때?")에 재확인 질문이 그대로 반복될 뿐 호응이 없음 — 원인 파악 완료, 수정은 보류(§아래 참고)

## 1. 목적과 범위

이 문서는 `scripts/test_prewalk_conversation.py`가 다뤄야 하는 대화 시나리오와 그 실행 결과를 함께 관리하는 단일 기준 문서다. 스크립트를 수정할 때는 먼저 이 문서의 시나리오 표를 갱신하고, 실행한 뒤에는 같은 표의 실행 결과 칸에 관측값을 기록한다.

- 이 스크립트는 로컬 PostgreSQL·Valkey와 실제 Kakao·OpenAI를 그대로 호출하는 수동 실행용이며, `tests/integration/test_api.py`처럼 mock Orchestrator로 자동 검증하는 것과는 성격이 다르다.
- `WeatherChecker`와 `RouteExecutor`(경로 엔진·profile 선택)는 이 문서의 범위가 아니다. 챗봇 대화 흐름(`Extractor`·`Interviewer`·`ConfirmationClassifier`)과 직결되는 부분만 다룬다.
- 모드 용어: `extraction.yaml` 기준으로 순환(`select_circular`), 편도(`select_oneway`, 목표 거리 포함), 편도 최단(`select_oneway_shortest`, 거리 무관 최단경로) 3종이다. `OnewayPreference` 스키마 docstring은 `select_oneway`를 "편도 우회 경로"라고도 부른다.
- agent_harness.md §9는 이 스크립트가 아닌 다른 방식(프런트엔드 연동 안드로이드 기기 등)으로 확인한 시스템 전체 검증 이력을 관리한다. 이 문서는 그 이력과 별개로 `scripts/test_prewalk_conversation.py` 실행 결과만 관리한다.

## 2. 시나리오와 실행 결과

| # | 카테고리 | 발화 | 검증 포인트 | 예상 결과 | 스크립트 반영 | 실행 결과 |
|---|---|---|---|---|---|---|
| 1 | 서비스 지역 밖 | "의정부역에서 3km 순환 산책하고 싶어" | 서울과 가까운 서울 밖 지명 처리(bbox 필터로 서울 밖 안내가 나오는지) | Extractor가 좌표를 채우지 않아 place_name만 남김 → Interviewer가 Kakao 검색(의정부역은 실제 좌표 lat≈37.738로 `_SEOUL_BBOX`의 `lat_max=37.70`을 벗어남) → bbox 필터로 걸러져 `out_of_seoul`에 잡힘 → "'의정부역' 위치는 서울 밖이라 출발지로 사용할 수 없어요..." | 반영됨 | 2026-08-03 7차 실행 확정: `out_of_seoul` 경로가 정상 동작함을 최종 확인 — origin="의정부역"(좌표 없음) → Kakao 검색 성공 → bbox 필터로 걸러짐 → is_complete=False 유지, response="'의정부역' 위치는 서울 밖이라 출발지로 사용할 수 없어요. 서울 내에서만 산책 경로를 추천해드릴 수 있어요. 출발하고 싶으신 다른 장소를 알려주시겠어요?" — 6차 실행에서 나왔던 "도착하고 싶으신 곳" 오문구(§아래 6차 실행 절 참고)가 target 태깅 수정 후 사라짐 |
| 2 | 무관한 발화(Extractor) | "주말에 볼만한 영화 추천해줘" (첫 턴, 산책 정보 없음) | 산책과 무관한 첫 발화 처리 | Extractor가 도구를 호출하지 않아 mode/context가 비어 있고 `is_complete=False` → `interview.yaml` 0번 규칙에 따라 짧게 호응한 뒤 산책 관련 대화만 가능하다고 안내 | 반영됨 | 2026-08-03. 2·3차 실행 모두 동일하게 확인: "LLM이 산책 모드를 결정하지 못했습니다"(도구 호출 없음) → mode=None → response="오, 주말에 영화 보시는 건 좋은 선택이네요! 저는 산책 이야기만 도와드릴 수 있어서요 — 어떤 산책을 원하시나요? 출발지나 목적지, 목표 거리 등을 알려주시면 최적의 경로를 제안해드릴게요." — 호응 + 리다이렉트 안정적으로 동작 |
| 3 | 무관한 발화(ConfirmationClassifier) | "여의도공원에서 2km 순환 코스로 산책할래" → "오늘 날씨 어때?" | 확인 대상과 무관한 응답이 부정으로 판정되는지 | 부정 판정 → `awaiting_confirmation=False`, `is_complete=False` → `Extractor` 재진입(기존 `user_context` 유지) | 반영됨 | 2026-08-03. 2·3차 실행 모두 동일: turn 2에서 Extractor가 도구 호출 없이 종료 → context가 turn 1과 완전히 동일하게 유지(target_km 2.0 그대로) → 같은 확인 질문이 그대로 재생성됨. 1차 실행의 target_km 오염 버그 재발 없음. 5차 실행(`_reconcile_location_arg` 적용 후)에서도 동일하게 재확인 — origin 좌표가 이제 Kakao 검증을 거쳐 채워짐(확정) |
| 4 | 모드-순환 | "여의도공원에서 2km 순환 코스로 산책하고 싶어" → "응" | `select_circular` 기본 흐름 | `select_circular` 추출 → "여의도공원에서 출발하는 2km 순환 산책이 맞나요?" 확인 질문 → 긍정 → `RouteExecutor` 진입, `route_result.status=success` | 반영됨 | 2026-08-02·03(3회 연속 동일): 추출·확인질문·긍정 판정·RouteExecutor 진입까지 챗봇 로직은 예상대로 동작. RouteExecutor가 `WalkRouteStatus.NO_NEAREST_START_NODE`로 실패했으나 경로 엔진 이슈로 이 문서 범위 밖. `response=경로를 생성했어요.`로 정상 표시. 5차 실행(`_reconcile_location_arg` 적용, origin이 Kakao로 재검증된 뒤)에도 동일하게 NO_NEAREST_START_NODE 재현 — LLM 좌표 부정확성 때문은 아니었던 것으로 확인(확정) |
| 5 | 모드-편도 | "성수역에서 뚝섬역까지 2km 정도 예쁜 강변길로 걷고 싶어" → "응" | `select_oneway`(target_km 포함) 기본 흐름 | `select_oneway`(target_km=2.0) 추출 → "성수역부터 뚝섬역까지가 맞나요?" 확인 질문 → 긍정 → `RouteExecutor` 진입 | 반영됨 | 2026-08-03. 크래시 없이 정상 동작 확인: `select_oneway`(target_km=2.0)로 origin·destination 모두 좌표까지 정확히 추출 → "성수역 2호선부터 뚝섬역 2호선까지가 맞나요?" → 긍정 → RouteExecutor 진입(NO_NEAREST_START_NODE, 범위 밖), `response=경로를 생성했어요.` — `Location` 문자열 coercion 수정 효과 확인. **주의**: 같은 시나리오를 한 번 더 돌렸을 때 destination이 "뚝섬역"이 아니라 "성수역"(origin과 동일)으로 잘못 추출된 사례가 있었으나(§4차 실행 절 참고), 이후 5차 실행(`_reconcile_location_arg` 적용 후, origin·destination 모두 Kakao로 재검증)에서는 재현되지 않음 — 확정하되 LLM 비결정성으로 인한 일회성 오류였을 가능성이 있어 계속 관찰 |
| 6 | 모드-편도 최단 | "잠실역에서 강남역까지 최단 경로로 가고 싶어" → "응" | `select_oneway_shortest`(target_km 없음) 기본 흐름 | `select_oneway_shortest` 추출(target_km 없음) → "잠실역부터 강남역까지가 맞나요?" 확인 질문 → 긍정 → `RouteExecutor` 진입 | 반영됨 | 2026-08-03. 정상 동작 확인: select_oneway_shortest(target_km 없음) 추출·확인질문·긍정 판정 모두 예상대로. RouteExecutor만 NO_NEAREST_START_NODE(범위 밖), `response=경로를 생성했어요.` 5차 실행(`_reconcile_location_arg` 적용 후)에도 동일하게 재확인(확정) |
| 7 | Interviewer-정보부족 | "편도로 2km 걷고 싶어" (목적지 없음) | 목적지 누락 시 재질문 | "편도" 명시로 select_oneway 선택, destination=null → `_missing_fields`에 "목적지 장소명 또는 좌표" 포함 → 목적지를 묻는 재질문, `is_complete=False` 유지 | 반영됨 | 2026-08-03. 의도대로 동작 확인: `mode=oneway_random`, `destination=None`으로 정상 추출(origin은 현재 위치로 기본 설정) → is_complete=False 유지 → response="편도로 2km 걷고 싶으시군요! ... 그런데 목적지에 대한 정보가 아직 없네요. 어떤 장소로 가고 싶으신가요?" — extraction.yaml "편도 명시 시 select_oneway 유지" 규칙 정상 작동 |
| 8 | Interviewer-검색실패 | "아리스토텔레스빌리지에서 걷고 싶어" (존재하지 않는 지명) | Kakao 검색 결과 0건일 때 반응 | `destination_candidate`가 채워지지 않아 목적지 정보 부족 상태로 재질문 예상. 정확한 안내 문구는 코드 근거가 약해 불확실 | 반영됨 | 2026-08-03. 크래시 없이 정상 동작 확인: origin="아리스토텔레스빌리지"(좌표 없음)만 채워지고 destination=None → 검색 결과 0건이라 `search_failures`에 origin만 기록 → response="'아리스토텔레스빌리지' 검색 결과가 없어요. 출발하고 싶으신 다른 장소를 알려주시면..." — 원인(존재하지 않는 지명)과 응답 근거가 정확히 일치. 이 시나리오는 애초에 place_name만 있고 좌표가 없어 `extractor.py` 좌표 신뢰 제거 수정의 영향을 받지 않음(재검증 우선순위 낮음) |
| 9 | Interviewer-다른 경로 요청 | Interviewer가 후보/제안을 준 상태에서 "다른 경로로 해줄 수 있어?" | 확정 전 대체 요청에 대한 반응 | 전용 처리 로직이 코드에 안 보여 가장 불확실. 발화가 무시되거나 무관한 발화처럼 취급될 가능성 | 반영됨 | 2026-08-03. 2·3차 실행 모두 동일: Extractor가 도구 호출 없이 종료 → 안국역 4km 컨텍스트가 그대로 유지되고 같은 확인 질문이 그대로 재생성됨. 요청 자체를 반영하진 않지만 기존 계획을 잃지 않고 안전하게 유지하는 동작으로 확인. 5차 실행(`_reconcile_location_arg` 적용, origin이 Kakao로 재검증된 뒤)에서도 동일하게 재확인(확정) |
| 10 | Interviewer-출발지=목적지 | "신촌역에서 신촌역으로 가는 길 알려줘" | origin=destination으로 동일하게 명시됐을 때 처리 방식 | 둘 다 location이 채워져 `_missing_fields`에 안 걸림 → "신촌역부터 신촌역까지가 맞나요?" 그대로 확인 질문 생성 → 긍정 시 `RouteExecutor` 진입(NO_NEAREST_START_NODE 가능성, 범위 밖) | 반영됨 | 2026-08-03. "용산역" 대신 "신촌역"으로도 동일하게 재현되어 일반화 확인: origin·destination 모두 "신촌역 2호선"(동일 좌표)으로 정확히 추출 → "신촌역 2호선부터 신촌역 2호선까지가 맞나요?" → 긍정 → RouteExecutor 진입(NO_NEAREST_START_NODE, 범위 밖), `response=경로를 생성했어요.` 5차 실행(`_reconcile_location_arg` 적용 후, origin·destination 모두 Kakao로 재검증)에서도 동일하게 재현(확정) |
| 11 | ConfirmationClassifier-애매한 긍정 | "광화문역에서 경복궁까지 가줘" → "그걸로 해줘" | 명시적 긍정 단어 없이도 긍정 판정되는지 | 명확한 실존 지명이라 destination이 정상 해결되어 확인 대기 상태(`awaiting_confirmation=True`)에 도달 → `confirmation.yaml`이 "그걸로 해줘"를 긍정으로 판정 → `is_complete=True` → `RouteExecutor` 진입 | 반영됨 | 2026-08-03 확정: destination="경복궁"(좌표 포함) 정상 추출 → "광화문역 5호선부터 경복궁까지가 맞나요?" 확인 대기 도달 → turn 2 "그걸로 해줘" → `is_complete=True`로 긍정 판정 → RouteExecutor 진입, `response=경로를 생성했어요.` — 원래 의도했던 애매한 긍정 판정이 최초로 검증됨. 5차 실행(`_reconcile_location_arg` 적용 후, destination이 Kakao 검색을 거쳐 재검증된 뒤)에도 동일하게 재현(확정) |

인증·세션·소유권 실패(만료 토큰, 없는 thread, 타 사용자 thread)와 Valkey TTL 만료는 이미 격리 환경에서 별도로 확인된 적이 있어([챗봇 경로 추천 Workflow](../architecture/workflows/prewalk_conversation.md) §6) 이 문서의 대상에 포함하지 않는다.

### 2026-08-02 1차 실행에서 발견한 문제

- **크래시(7, 9번)**: 목적지 없이 편도/편도 최단 요청이 Extractor에 들어가면 `select_oneway`/`select_oneway_shortest` tool이 `destination=None`으로 호출돼 Pydantic `ValidationError`로 대화가 끊긴다(`status=INTERNAL_ERROR`). 두 시나리오 모두 원래 검증하려던 내용(재질문, 대체 요청 반응)을 확인하지 못했다.
- **Extractor가 무관한 발화에도 기본값을 채움(2, 3번)**: "오늘 뭐 먹지?"·"오늘 날씨 어때?"처럼 산책과 무관한 발화에도 `select_circular(target_km=3.0 기본값, origin=현재위치)`가 채워지며, 재질문 없이 확인 대기 상태로 진행되거나 기존 `target_km`이 사용자 동의 없이 바뀐다.
- **시나리오가 의도한 상황을 재현하지 못함(10, 11번)**: 10번은 origin의 "~에서" 표현이 무시돼 origin=destination 동일 명시 케이스가 재현되지 않았고, 11번은 destination이 Kakao에서 해결되지 않아 확인 대기 상태 자체에 도달하지 못해 애매한 긍정 판정이 검증되지 않았다.
- 4, 5, 6, 10번의 `RouteExecutor` 단계 `NO_NEAREST_START_NODE` 실패는 경로 엔진 이슈로 이 문서 범위 밖이며, 챗봇 쪽(추출·확인질문·판정) 로직 자체는 이 네 시나리오에서 예상대로 동작했다.
- **RouteExecutor 이후 response 미갱신(4, 5, 6, 10번)**: `route_executor.py`는 `state.route_result`와 `state.profile`만 쓰고 `state.response`는 성공·실패와 무관하게 전혀 갱신하지 않는다. 그 결과 확인 질문에 긍정해 `RouteExecutor`가 실행된 뒤에도 사용자에게 보이는 `response`는 turn 1의 확인 질문 문구 그대로 남는다.
- **상태와 어긋나는 응답 문구(11번)**: turn 2 "그걸로 해줘" 처리 후 `context`(destination 좌표 없음)·`awaiting_confirmation`·`is_complete`·`route_result` 모두 turn 1과 동일해 실질적으로 아무 진행이 없었는데도, `response`는 "산책 코스를 준비할게요"라며 진행되는 것처럼 답한다. `Interviewer`의 2차 자유 생성 호출(`interview.yaml`, tool 미바인딩)이 실제 필드 상태를 반영하지 않고 문구를 만들어내는 것이 원인으로 추정된다.

### 2026-08-02 ~ 2026-08-03 사이에 적용한 수정

- `mode_tools.py`: `select_oneway`/`select_oneway_shortest`의 `destination`(과 `origin`·`target_km`)을 `Optional`로 완화해 destination=None 크래시(7·9번 원인) 해결
- `extraction.yaml`: 무관/막연한 발화에는 도구를 호출하지 않는 최우선 규칙 추가(2·3번), origin 우선순위 규칙 추가(10번), "편도" 명시 시 목적지 없어도 select_oneway를 선택하는 규칙 추가(7번 재발견 문제)
- `interview.yaml`: 무관한 주제(기존 context 없음)일 때 짧게 호응 후 산책 화제로 유도하는 0번 규칙 추가(2번), "아는 체" 지침 제거(11번 상태-응답 불일치 완화)
- `interviewer.py`: 검색 결과 0건(`search_failures`)과 검색은 됐지만 서울 밖(`out_of_seoul`)을 구분해 하드코딩 안내 문구로 즉시 재질문(1·8번)
- `scripts/test_prewalk_conversation.py`: `route_result` 존재 시 `response=경로를 생성했어요.`로 표시(4·5·6·10번), 2번 발화를 few-shot 예시와 겹치지 않게 교체, 1번 발화를 정확한 지명으로 교체

### 2026-08-03 2차 실행에서 새로 발견한 문제

- **새 크래시 유형(5, 8번)**: 1차 실행 때 없던 크래시. `select_oneway`/`select_oneway_shortest` 호출 시 LLM이 `origin`/`destination`을 `Location` dict가 아니라 장소명 문자열만 반환해 Pydantic ValidationError 발생(`destination=None` 크래시와는 다른 원인). `Location`에 문자열을 `place_name`으로 자동 변환하는 `model_validator`를 추가하고, `extractor.py`의 tool 호출도 try/except로 감싸 수정(2026-08-03). 재검증 필요
- **7번 시나리오 전제 무효화**: 크래시는 해결됐지만 "목적지 없이 거리만 언급하면 무조건 select_circular"라는 기존 규칙이 "편도"라는 명시적 단어보다 우선 적용돼, 목적지 재질문 대신 조용히 순환 모드로 바뀌는 문제 발견. extraction.yaml에 "편도가 명시되면 목적지 없어도 select_oneway 선택, destination은 null" 규칙 추가(2026-08-03). 재검증 필요
- **1번 시나리오 발화 오류**: "부산 해운대"라는 부정확한 표현 때문에 Kakao 검색 자체가 0건이라 `out_of_seoul` 경로가 검증되지 않음("검색 결과 없음"과 "서울 밖"을 구분하려던 원래 목적을 달성 못함). "해운대해수욕장"(정확한 지명)으로 교체, 재검증 필요

### 2026-08-03 few-shot 예시와 겹치는 시나리오 정리

시나리오를 프롬프트 수정 근거로 삼아 extraction.yaml에 예시를 추가하는 과정에서, 그 예시와 같은(또는 거의 같은) 문구를 시나리오 발화로 계속 쓰고 있었다는 걸 뒤늦게 발견했다. 이 상태로 실행하면 "규칙을 일반화했는지"가 아니라 "few-shot 예시를 그대로 암기했는지"만 확인하게 되므로 발화를 교체했다.

- **7번**: "3km 편도로 산책하고 싶어"가 extraction.yaml에 추가한 예시와 완전히 동일한 문구 → "편도로 2km 걷고 싶어"로 교체
- **10번**: "용산역에서 용산역으로 가는 길 알려줘"가 extraction.yaml 예시와 완전히 동일한 문구 → "신촌역에서 신촌역으로 가는 길 알려줘"로 교체
- **6번**: "구파발역에서 연신내역까지"가 extraction.yaml 예시와 출발지·목적지 조합이 동일 → "잠실역에서 강남역까지"로 교체
- **5번**: "홍대에서 합정역까지 3km"가 extraction.yaml 예시("홍대에서 신촌까지 3km")와 출발지·거리가 동일 → "성수역에서 뚝섬역까지 2km"로 교체

### 2026-08-03 3차 실행: 9개 시나리오 확정, 남은 2개 재작성

2·3·4·5·6·7·8·9·10번은 이번 실행에서 모두 예상 결과와 일치해 확정했다(크래시 없음, few-shot 암기가 아닌 일반화 확인). 남은 두 시나리오는 발화 자체의 한계로 여전히 의도한 상황을 검증하지 못해 다시 교체했다.

- **1번**: "부산 해운대"에 이어 정확한 지명 "해운대해수욕장"으로 바꿔도 여전히 `search_failures`("검색 결과 없음")로만 빠졌다. 원인은 지명 정확도가 아니라 **Kakao 키워드 검색이 검색 기준 좌표(이 시나리오에서는 서울시청, 현재 위치) 근처로 결과를 제한하는 것으로 추정**된다는 점 — 300km 이상 떨어진 실존 장소는 정확한 이름을 줘도 검색 결과 자체가 안 나온다. `out_of_seoul` 경로(검색은 되지만 bbox로 걸러지는 경우)를 실제로 검증하려면 서울과 인접해 검색 반경 안에 드는 지명이 필요해 "화정고등학교"(고양시)로 교체했다.
- **11번**: "인스타 감성 카페거리"는 애초에 실존하는 단일 장소명이 아니라 두 차례 실행 모두 Kakao 검색이 실패했다. 확인 대기 상태 자체에 도달하지 못해 "그걸로 해줘"의 애매한 긍정 판정을 한 번도 검증하지 못한 상태 → 명확한 실존 지명 "경복궁"으로 교체했다.

### 2026-08-03 4차 실행: out_of_seoul 구조적 문제와 5번 목적지 오추출

11번은 "경복궁"으로 교체 후 완전히 확정됐다(애매한 긍정 판정 최초 검증). 1번은 "화정고등학교"(서울 인접 실존 지명)로 바꿨는데도 확인 대기 상태로 곧장 진입해, 원래 의도였던 `out_of_seoul` 경로가 여전히 검증되지 않았다.

- **`out_of_seoul` 구조적 문제(1번)**: `Interviewer._is_complete`는 순환 모드에서 `origin`에 좌표가 있고 `target_km`만 있으면 곧바로 "완료"로 판단해 확인 질문을 만든다(`interviewer.py`). `is_within_seoul_bbox` 검증은 `Interviewer._execute_tool_calls`(Kakao 검색 경로) 안에만 있는데, Extractor의 LLM이 유명한 장소의 좌표를 스스로 채워버리면 이 검색 경로 자체를 타지 않는다. 실제로 지금까지 성공했던 5·6·9·10·11번(성수역·잠실역·안국역·신촌역·경복궁 등)도 전부 LLM이 좌표를 직접 채운 경로였다. 즉 "서울 밖 실존 지명"을 검색 단계에서 걸러내려던 설계가 유명한 장소에는 아예 작동하지 않는 구조였다.
  - **수정**: `extractor.py`에 `_reconcile_location_arg`를 추가했다(최초 `_strip_untrusted_coordinates`에서 이름·로직 보강). LLM이 tool 호출 인자에 스스로 채운 좌표는 (1) `state.current_location`과 정확히 일치하면("여기"/"현재 위치" 처리) 그대로 신뢰, (2) place_name이 직전 State(재진입 전 `state.user_context`)의 값과 같으면(같은 장소 재언급) 새로 채운 좌표 대신 직전에 이미 확정된 좌표로 덮어써 재검색을 피하면서 헛채움도 막고, (3) 그 외(새로 언급된 장소, 또는 비교할 직전 값 없음)에는 좌표를 지워 place_name만 남긴다. 이렇게 하면 새로 언급된 이름 있는 장소는 예외 없이 Interviewer의 Kakao 검색·bbox 검증을 거치고, 이미 확정된 장소를 다시 언급했을 때는 불필요한 재검색 없이 기존 값이 유지된다.
  - **파급 범위**: 이 변경으로 실존 장소가 등장하는 1·3·4·5·6·8·9·10·11번 전부 데이터 경로가 바뀌었다. 8번은 애초에 좌표 없는 place_name만 다뤄 영향이 없고, 11번은 이미 이번 실행에서 confirm까지 확정돼 재검증 우선순위가 낮다. 나머지는 5차 실행에서 재확인이 필요하다. RouteExecutor의 `NO_NEAREST_START_NODE`가 실은 LLM이 부정확하게 채운 좌표 때문이었을 가능성도 있어, Kakao 검증을 항상 거치면 이 실패율이 달라질 수도 있다(확인 필요, 확정 아님).
- **5번 목적지 오추출(재현 여부 미확인)**: 같은 시나리오("성수역에서 뚝섬역까지")를 두 번째로 돌렸을 때 destination이 "뚝섬역"이 아니라 origin과 동일한 "성수역 2호선"으로 추출돼 "성수역 2호선부터 성수역 2호선까지가 맞나요?"라는 잘못된 확인 질문이 나갔다(크래시 없이 그대로 진행됨). 원인이 코드에 있지 않고(exception 로직은 destination을 건드리지 않음) LLM 추출 자체의 실수로 보인다. 재현 여부를 아직 확인하지 못했다.

### 2026-08-03 "여기"/"현재 위치" 처리 방식 변경

`extraction.yaml`의 origin 규칙 3번이 원래 "위치 대명사만 언급되면 [Current Location] 정보를 그대로 사용"(LLM이 current_location 값을 직접 베껴 채움)이었는데, LLM이 값을 정확히 복사한다는 보장이 없어 불안정했다. `origin을 null로 두세요(시스템이 자동 대체)`로 바꾸고, `extractor.py`의 기존 예외5(`args.get("origin") is None` → `state.current_location.model_dump()`)가 항상 정확한 GPS 값으로 채우도록 일원화했다. `extraction.yaml`/`extractor.py`의 `input_variables`에서도 `current_location`을 제거해 LLM이 애초에 좌표를 볼 필요조차 없앴다. 7번 시나리오("편도로 2km 걷고 싶어", 위치 언급 없음)가 이 경로를 검증한다.

### 2026-08-03 5차 실행: 근본 원인 규명 — `_SEOUL_BBOX`가 고양시를 포함

1번을 "화정고등학교"로 재실행해도 여전히 `is_complete=True`로 곧장 확인 질문이 나가 `out_of_seoul`이 검증되지 않았다. `_reconcile_location_arg`에 진단 로그를 추가해 실제로 호출되는지부터 확인한 결과(캐시 삭제는 무관했음):

```
[DIAG] _reconcile_location_arg 호출됨: loc_arg={'place_name': '화정고등학교'}, prior_loc=None
[DIAG] 새로운 장소 -> 좌표 제거: {'place_name': '화정고등학교', 'lat': None, 'lon': None, 'address': None}
```

`_reconcile_location_arg`는 정상적으로 좌표를 지웠고, 이후 `Interviewer`가 Kakao 검색까지 정상 실행했다. 문제는 그다음이었다 — `src/interfaces/validators/coord_validator.py`의 `_SEOUL_BBOX`(`lat 37.41~37.70, lon 126.73~127.27`)가 서울의 "최소 외접 사각형"(1차 빠른 판단용)인데, 서울이 직사각형이 아니라서 바로 인접한 고양시 화정동(37.636, 126.828)도 이 사각형 안에 포함돼버린다. 즉 `is_within_seoul_bbox`가 "서울 밖" 판정에 실패한 게 아니라, **이 사각형 자체가 서울과 맞닿은 지역까지 느슨하게 포함하도록 설계돼 있었다**(코드 주석에 이미 "1차 빠른 판단"이라 명시돼 있고, PostGIS 폴리곤 기반 2차 정밀 검증 `validate_seoul_polygon_contains`가 별도로 존재하지만 `Interviewer`는 이를 쓰지 않는다).

`_reconcile_location_arg`·`extractor.py`·`interviewer.py`의 로직 자체는 모두 정상이었음이 이 과정에서 확인됐다(2~11번 10개 시나리오 전부 확정). 1번만 bbox 사각형을 확실히 벗어나는 지명("의정부역", lat≈37.738 > lat_max 37.70)으로 교체해 재검증이 필요하다. 진단 로그는 원인 규명 후 제거했다.

**향후 고려 사항(미결정)**: `Interviewer`가 느슨한 1차 bbox 대신 정밀한 폴리곤 검증을 쓰도록 바꾸면 이런 경계 지역 오탐을 근본적으로 없앨 수 있지만, DB 세션이 필요해 더 큰 변경이 된다. 지금은 시나리오 발화를 bbox 밖으로 확실히 벗어나는 지명으로 고르는 우회로 대응했다.

### 2026-08-03 6차 실행: out_of_seoul 확정 + target 오태깅 버그 수정

1번을 "의정부역"으로 재실행한 결과 `out_of_seoul` 경로가 최초로 정상 동작했다(11개 시나리오 전부 확정). 다만 응답 문구가 "출발하고 싶으신 곳과 **도착하고 싶으신 곳**을 다시 알려주시겠어요?"로 나왔는데, 이 시나리오는 순환(circular) 모드라 애초에 destination 개념이 없다.

원인은 `Interviewer._execute_tool_calls`의 `target = args.get("target", "destination")`이었다. `.get(key, default)`는 키가 아예 없을 때만 default를 쓰는데, LLM이 tool 호출 인자에 `target: null`을 명시적으로 채워 보내면 키는 존재하므로 default가 적용되지 않고 `None`이 그대로 쓰인다. 이번 실행에서 LLM이 origin 검색을 이런 식으로 태깅해(또는 잘못 "destination"으로 태깅해) 호출한 것으로 보이고, 그 결과가 bbox에 걸려 `out_of_seoul["destination"]`에 기록됐다. 곧이어 2번 경로(자동 보완)가 origin도 별도로 검색·필터링해 `out_of_seoul["origin"]`에도 같은 지명이 들어가면서, `_build_out_of_seoul_message`가 "origin·destination 둘 다 서울 밖" 분기를 타 destination이 없는 모드에도 "도착지" 문구가 나갔다.

**수정**: `interviewer.py`에서 `target = args.get("target") or "destination"`로 바꿔 `None`도 default 적용 대상이 되도록 하고, `state.user_context`에 `destination` 속성이 아예 없는 모드(circular)에서는 `target`을 무조건 `"origin"`으로 강제하도록 방어 코드를 추가했다. `hasattr(CircularPreference_instance, "destination")`이 `False`임을 직접 확인해 반영했다.

### 2026-08-03 7차 실행: 최종 확정

1번을 재실행해 문구가 "'의정부역' 위치는 서울 밖이라 출발지로 사용할 수 없어요... 출발하고 싶으신 다른 장소를 알려주시겠어요?"로, "도착지" 언급 없이 정상적으로 나오는 것을 확인했다. 2~11번도 기존 확정 결과와 동일하게 재현됐다. 이것으로 11개 시나리오 전부 확정 상태다.

### 알려진 미해결 UX 이슈(보류): 재확인 중 무관한 발화에 호응 없음(3번)

3번(확인 대기 중 "오늘 날씨 어때?")은 판정·State 값 자체는 예상대로 동작하지만(부정 판정 → 재확인 질문 재생성), 응답 문구가 turn 1과 완전히 동일한 확인 질문만 반복하고 "날씨"라는 발화 내용에는 전혀 호응하지 않는다.

**원인**: `ConfirmationClassifier`가 부정 판정 → `Extractor`가 이번 턴엔 아무것도 추출하지 않고(정상) → `Interviewer`는 `state.user_context`가 여전히 완전(complete)하다고 보고 `interview.yaml`(LLM 호출, 호응 로직이 있는 곳)을 아예 거치지 않은 채 완전히 하드코딩된 `_build_confirmation_message`로 바로 확인 질문을 재생성한다. 이 함수는 `user_prompt`를 보지 않으므로 호응이 구조적으로 불가능하다.

**검토했던 수정 방향(보류)**: `State`에 "이번 턴에 실제로 뭔가 추출됐는지" 플래그를 추가하고, `Interviewer`가 `is_complete=True`인데 이번 턴엔 아무것도 못 뽑은 경우(=재확인 상황)에만 짧은 호응을 LLM으로 생성해 확인 질문 앞에 붙이는 방식. 크래시·오작동이 아니라 UX 다듬기 수준이라 우선순위를 낮춰 보류하기로 함(2026-08-03).

## 3. 관리 원칙

- 스크립트의 `SCENARIOS`를 추가·삭제·수정하면 같은 작업에서 위 표의 "스크립트 반영" 칸도 갱신한다.
- 시나리오를 실행하면 "실행 결과" 칸에 확인 날짜·환경(로컬/격리, 사용한 DB·외부 API)과 관측값(판정 결과, 오류 메시지 등)을 기록하고, "예상 결과"와 다르면 그 차이를 함께 적는다. 일회성 관측값은 고정 기대값처럼 쓰지 않는다.
- "예상 결과"가 코드 근거 없이 추측이었던 항목은 실행 후 실제 근거로 대체한다. 크래시로 검증 자체가 안 된 항목(현재 7, 9번)과 의도한 상황이 재현되지 않은 항목(현재 10, 11번)은 "예상 결과"를 그대로 두고 재작성·재실행 후 갱신한다.
- 새 시나리오를 추가하면 번호를 이어서 붙이고 "스크립트 반영"은 "미반영", "실행 결과"는 "미실행"으로 시작한다.
- 시나리오 실행 결과를 근거로 `extraction.yaml`/`interview.yaml`에 few-shot 예시를 추가하면, 그 시나리오의 발화가 예시와 겹치지 않는지 확인한다. 겹치면 같은 검증 포인트를 유지한 채 발화만 바꾼다(암기가 아닌 일반화를 확인하기 위함).

## 4. 완료 기준

- 표의 번호·카테고리·발화가 `scripts/test_prewalk_conversation.py`의 `SCENARIOS`와 정확히 일치한다(반영됨으로 표시된 항목 기준).
- 모든 "반영됨" 시나리오에 확인 날짜가 있는 실행 결과가 있고, 예상 결과와 실제 결과의 일치 여부가 기록돼 있다.
- 미반영 시나리오는 왜 아직 다루지 않았는지 검증 포인트만으로 판단 가능하다.
