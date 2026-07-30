# 챗봇 Agent 하드코딩 문구 처리 방안 제안

> 상태: Proposal  
> 기준일: 2026-07-30  
> 기준 문서: [현재 챗봇 Agent 하네스](../chatbot/agent_harness.md), [챗봇 Agent 업그레이드 제안](../proposals/chatbot_upgrade_proposal.md), [챗봇 Agent 불필요한 항목 제거 제안](../proposals/chatbot_cleanup_proposal.md)  
> 대상 코드: `src/agent/nodes/extractor.py`, `src/agent/nodes/interviewer.py`, `src/service/chat/prewalk_service.py`

## 1. 목적과 범위

LLM에게 응답을 요청하지 않고, 하드코딩된 문자열을 사용하는 코드를 각 파일별로 찾아내고, 이를 해결할 수 있는 방안(후속 조치)을 마련하여 우선순위(상, 중, 하)를 매기고자 한다.
하드코딩된 문자열을 해결할 수 있는 방안으로는 그 역할을 수행하는 노드를 추가하는 것으로 한다.
이후 추가되거나 개선된 노드를 기반으로 `prewalk_service.py` 내에서 챗봇 노드와 엣지를 재정의하고자 한다.


범위:

- `src/agent/nodes/extractor.py`
- `src/agent/nodes/interviewer.py`
- `src/service/chat/prewalk_service.py`

제외:

- 노드를 추가하거나 개선하는 것은 오로지 하드코딩 해결에만 초점이 맞춰져야 하며, 새로운 기능이 생긴다거나 기존 기능이 없어지는 일은 없어야 한다.
- `frontend/**`
- 이 문서만으로 승인되지 않은 코드 변경

## 2. 발견 목록

| ID | 대상 | 현재 하드코딩 사실 | 해결 방안(추가/개선할 노드) | 우선순위(상/중/하) | 상태 | 후속 조치 |
|---|---|---|---|---|---|---|
| 1 | `prewalk_service.py:23-29,49-58` `_NEGATIVE_WORDS`/`_POSITIVE_WORDS`, `_is_positive_response` | `awaiting_confirmation=True` 상태에서 사용자 응답의 긍정/부정 여부를 고정된 한국어 단어 목록 포함 여부로만 판정함. 목록에 없는 표현("굿", "그걸로 해줘" 등)은 부정으로도 긍정으로도 못 잡아 `_is_positive_response`가 `False`로 떨어짐(부정 처리) | 신규 노드 `ConfirmationClassifier` 추가. `state.awaiting_confirmation=True`일 때 사용자 응답을 신규 프롬프트 `src/prompt/confirmation.yaml`(입력: `user_input`, `current_context`)로 LLM 분류해 `is_positive` 등 구조화 출력을 받음. `_NEGATIVE_WORDS`/`_POSITIVE_WORDS`는 제거 | 상 | 결정 완료 | 노드 이름 `ConfirmationClassifier`로 확정(2026-07-30 논의). 그래프 편입은 3번 항목 참고. 구현은 팀 승인 후 별도 작업 단위에서 진행 |
| 2 | `interviewer.py:179-204` `_build_confirmation_message`, `_is_same_location`(170-177) | 모드별(`OnewayShortestPreference`/`OnewayPreference`/`CircularPreference`) 확인 질문 문구가 전부 Python f-string 템플릿으로 고정됨. `interview.yaml` LLM 호출을 거치지 않고 이 메서드가 `state.response`를 직접 채움(호출부 2곳: `interviewer.py:53`, `interviewer.py:97`) | `interview.yaml` 확장(LLM 호출)으로 바꿔도 어차피 `current_context`를 그대로 요약해 "~가 맞나요?" 형태로 되돌려주는 것이라 결과 문구가 지금 f-string과 실질적으로 동일할 것으로 판단됨. LLM 호출 지연시간·비용만 늘고 실익이 없어 하드코딩 유지 | 하 | 결정 완료 | 하드코딩 유지로 최종 결정(2026-07-30 논의, 처음엔 interview.yaml 확장으로 검토했으나 결과 동일성 판단 후 번복) |
| 3 | `prewalk_service.py:_build_graph`, `PrewalkOrchestrator.orchestrator`의 `awaiting_confirmation` 분기(166-187줄) | `_build_graph`가 정의한 LangGraph(`extractor → interviewer → (조건부) route_executor`)에 confirmation 판정 단계가 없음. `orchestrator()`가 `awaiting_confirmation`을 보고 Python if/else로 그래프 실행 자체를 우회해 `route_executor.run()`을 직접 호출하거나 고정 문구를 반환함 — 그래프 선언과 실제 실행 경로가 불일치(`chatbot_cleanup_proposal.md` #3과 동일 증상) | `set_conditional_entry_point`로 진입점을 분기: `awaiting_confirmation=True → confirmation_classifier`, `False → extractor`. `confirmation_classifier`의 조건부 엣지로 긍정 시 `route_executor`, 부정 시 `interviewer`(질문 재생성)로 연결하고 orchestrator의 수동 우회 분기는 제거 | 상 | 결정 완료 | 1번(`ConfirmationClassifier`) 신설과 짝을 이룸(2026-07-30 논의). 이 재배선으로 5번(구 4번)의 하드코딩된 되묻기 문구를 `interviewer`가 대체 가능해짐 |
| 4 | `prewalk_service.py:173` `state.response = "경로를 생성하고 있어요. 잠시만 기다려주세요 🗺️"` | 긍정 응답 직후 `route_executor.run` 호출 전에 고정 문자열을 `state.response`에 대입. `route_executor.run()`은 `state.response`를 갱신하지 않으므로(LLM 호출 제거됨), 이 문구가 `route_result`와 함께 그대로 응답에 실려 나감(응답 시점엔 이미 경로 생성이 끝난 상태라 "기다려주세요" 문구가 실제 타이밍과 불일치) | `state.response` 재할당 라인 자체를 제거. 직전 턴에서 `interviewer`가 만든 확인 질문 문구(`state.response`)가 그대로 유지된 채 `route_result`만 채워져 응답됨. 별도 문구 신설 불필요 | 하 | 결정 완료 | 하드코딩 문자열 제거로 최종 결정(2026-07-30 논의). Streamlit 프로토타입 대신 실제 모바일 앱과 연동 중이며 앱은 별도 저장소(`frontend/mobile_app/README.md` 확인 결과 이 저장소엔 스텁만 있음)라, 빈 응답/재사용된 응답의 실제 렌더링 방식은 이 저장소에서 확인 불가 — 필요 시 모바일팀 확인 |
| 5 | `prewalk_service.py:186` `state.response = "알겠어요. 어떤 부분을 바꿀까요? 출발지, 목적지, 거리 중 원하는 내용을 다시 알려주세요."` | 부정 응답 시 무엇을 바꿀지 되묻는 문구가 고정 문자열. LangGraph를 우회하는 분기(`prewalk_service.py:179-187` 주석)라 `interviewer.py`를 거치지 않음 | 3번의 그래프 재배선으로 부정 응답이 `interviewer` 노드로 흘러가면, 기존 "정보 부족 시 질문 생성" LLM 로직이 이 되묻기를 대체함. 별도 신규 노드 불필요 | 중 | 결정 완료 | 3번 구현 시 함께 해결됨(구현 별도 항목 아님) |
| 6 | `interviewer.py:19` `_FALLBACK_RESPONSE = "죄송해요, 일시적인 오류가 발생했어요. 잠시 후 다시 시도해 주세요."` | `interview.yaml` LLM 호출 자체가 실패했을 때(`interviewer.py:64-67`)의 대체 문구 | LLM 호출이 실패한 상황이라 이 문구를 다시 LLM으로 생성하는 것은 실패 원인과 상충함. 하드코딩 유지 | 하 | 결정 완료 | 하드코딩 유지로 최종 결정(2026-07-30 논의) |
| 7 | `extractor.py:60` `_EXPLICIT_ORIGIN_MARKERS = ("에서", "부터", "출발", "시작")` | origin/destination 장소명이 같을 때 명시적 출발 표현이 있는지 판정하는 고정 한국어 조사/단어 목록(`extractor.py:61-72`). 추가 LLM 호출 없이 `extraction.yaml` 결과에 대한 순수 Python 후처리 검증임 | 이 보정은 LLM 호출이 이미 끝난 뒤의 결정론적 안전망이라 제거하지 않고 유지. 대신 `extraction.yaml` 프롬프트에 "출발지·목적지가 같은 장소명이면 명시적 출발 표현이 있을 때만 origin을 채워라" 지침을 추가해,애초에 LLM이 실수할 확률 자체를 낮춤. `_EXPLICIT_ORIGIN_MARKERS`는 하드코딩이지만 그대로 유지 | 하 | 결정 완료 | 프롬프트 개선 + Python 안전망 유지로 확정(2026-07-30 논의). `extraction.yaml` 지침 추가는 별도 구현 작업으로 진행 |
| 8 | `interviewer.py:141-168` `_is_complete`/`_get_missing_info` | `_is_complete`가 계산한 boolean 결과를, `_get_missing_info`가 "출발지 장소명 또는 좌표" 등 고정 한국어 문구 조합으로 다시 번역해 `interview.yaml`의 `missing_info` 변수로 전달함(`interviewer.py:45`) | LLM 응답을 대체하는 코드가 아니라 LLM 입력을 구성하는 정상적인 코드로 판단해 하드코딩 유지. `_is_complete`의 boolean 로직도 그대로 둠 | 하 | 결정 완료 | 하드코딩 유지로 최종 결정(2026-07-30 논의) |

각 행은 코드 대조로 확인한 사실만 채우고, 확인하지 못한 항목은 빈 값 대신 "미확인"과 확인 방법을 적는다. "상태"는 미착수/조사 중/결정 완료/완료로 표기하고, 코드 변경이 있었으면 후속 조치 칸에 실제로 한 일을 기록한다.

## 3. 조사 완료 기준

- 발견 목록의 모든 대상이 "현재 하드코딩 사실"과 "해결 방안"까지 채워진다.
- "미확인"으로 남은 항목이 없다. 남아 있다면 확인 방법과 함께 다음 조사 대상으로 표시한다.

## 4. 승인과 구현 완료 기준

- 팀이 발견 목록의 각 항목별 노드 추가·개선 여부(또는 하드코딩 유지 여부)를 승인한다.
- 승인된 항목만 별도 구현 작업 단위로 옮기고, 이 Proposal 문서는 승인 이력만 남긴다.
- 이 Proposal 자체는 코드를 변경하지 않으며, 구현은 승인 후 별도 커밋에서 진행한다.
- 노드 추가·개선 후에는 `prewalk_service.py`의 Graph 노드·엣지 정의를 함께 갱신하고, [챗봇 Agent 하네스](../chatbot/agent_harness.md)의 State·Node·Edge 계약도 코드와 일치시킨다.