# 챗봇 Agent 불필요한 파라미터, 함수, 코드, 노드, 프롬프트 등 제거 제안

> 상태: Proposal  
> 기준일: 2026-07-29  
> 기준 문서: [현재 챗봇 Agent 하네스](../chatbot/agent_harness.md), [챗봇 Agent 업그레이드 제안](../proposals/chatbot_upgrade_proposal.md)  
> 대상 코드: `src/agent/`, `src/service/chat/prewalk_service.py`, `src/schema/prewalk_schema.py`

## 1. 목적과 범위

`src/agent/`, `prewalk_service.py`, `prewalk_schema.py`에서 현재 사용되지 않는 파라미터·함수·코드·Node·Prompt 항목을 확인하고, 제거 시 리스크와 후속 조치 필요 여부를 표로 정리한다. 이 문서는 조사와 제안까지만 다루며, 이 문서 자체로 코드를 변경하지 않는다.

`chatbot_upgrade_proposal.md`의 P7(Prompt·Tool·Graph 검증과 잔재 정리)과 대상 범위가 겹치므로, 이 문서의 발견 목록을 P7 실행 시 입력으로 사용한다.

범위:

- `src/agent/nodes/`가 `src/prompt/{프롬프트}.yaml`에 넘기지만 실제로 프롬프트 안에서 쓰이지 않는 `input_variables`
- BE가 FE로 넘기는 LLM 응답 중 다른 응답에 가려져 실제로 쓰이지 않는 응답
- 역할이 동일한 두 Node 중 불필요한 쪽
- `src/agent/tools/`에서 실제로 호출되지 않는 Tool
- `prewalk_service.py`에서 실제로 쓰이지 않거나 없어도 무방한 코드·함수
- `prewalk_schema.py`의 State 필드 중 실제로 쓰이지 않거나 중복되거나 불필요하게 남아 있는 필드

제외:

- 하드코딩된 문자열 분리 — [Node 분리 제안](../proposals/chatbot_node_proposal.md)에서 별도로 다룬다
- `frontend/**`
- 이 문서만으로 승인되지 않은 코드 변경

## 2. 발견 목록

| ID | 대상 | 현재 사실 | 제거 근거 | 리스크(상/중/하) | 후속 조치 |
|---|---|---|---|---|---|
| 1 | `src/prompt/complete.yaml` | `prompt_name="complete"` 호출부가 `src/` 전체에 0건(`route_executor.py:64` 주석에만 언급) | 어디서도 로드·호출되지 않는 프롬프트 파일 | 하 | 파일 삭제만으로 충분. `chatbot_upgrade_proposal.md` P7 실행 시 재확인 |
| 2 | `src/prompt/route_result.yaml`, `route_executor.py:65-73`(주석 블록) | 호출 코드가 전부 주석 처리되어 있고 활성 호출부 없음 | 런타임에 도달 불가능한 죽은 프롬프트·코드 | 중 | `chatbot_upgrade_proposal.md` D1(확인 흐름) 결정 후 주석 블록 삭제 또는 기능 복원 여부 결정 |
| 3 | `PrewalkOrchestrator._build_graph`의 `route_executor` 노드 등록·조건부 엣지(`prewalk_service.py:69,75-80`) | `Interviewer.run`은 `is_complete=True`를 만들지 않음(`interviewer.py:52,96,118` 모두 `False`) → `self.graph.ainvoke` 경로에서 `route_executor`에 도달 불가. 실제 실행은 `orchestrator()`의 수동 우회(`prewalk_service.py:181`)뿐 | Graph 선언과 실제 실행 경로가 불일치하는 배선 | 중 | `chatbot_upgrade_proposal.md` D1 선택(확인 흐름 통합 vs 도달 불가 엣지 제거)에 따라 처리 방식이 달라짐 |
| 4 | `Interviewer.run`의 `raw_response.content`(`interviewer.py:59-116`) | `tool_calls`가 있으면(`candidates` truthy) `raw_response.content`는 최종 응답에 반영되지 않고 `_build_confirmation_message` 또는 `location_formatter` 응답으로 대체됨 | LLM 호출 결과 중 일부가 다른 응답에 가려져 사용되지 않는 경우(범위 2번 항목) | 중 | tool_calls 존재 시 `.content`를 애초에 요청하지 않도록 구조 변경 필요 여부 판단 |
| 5 | `State.weather_data`(`prewalk_schema.py:68`) | 쓰기 1건(`prewalk_service.py:130`)만 있고 `src/` 전체에서 읽는 코드 없음 | write-only 필드 | 중 | API 응답·Valkey 저장 payload에 이미 포함되어 있어 프론트 참조 여부 확인 필요, 제거 시 `get_init_message`(`prewalk_service.py:127-132`) 함께 수정 |
| 6 | `BasePreference.purpose`(`prewalk_schema.py:24`) | 유일한 쓰기(`extractor.py:82`)가 이전 턴 값을 그대로 복사만 하고, 어떤 Tool도 `purpose` 인자를 받지 않아 항상 `None` | 실질적으로 항상 null인 필드 | 중 | `interview.yaml:33` 문구, `extractor.py:82` 코드 제거 필요, API 응답 포함 여부로 프론트 참조 확인 필요 |
| 7 | `PlaceTool.get_address_from_coords`/`get_address_from_category`(`place_tools.py:19-25,39-52`) | 정적 호출부 없음, LLM의 동적 tool-call 디스패치(`interviewer.py:224`)로만 도달 가능 | 정적 분석상 미사용으로 보이나 동적 호출 가능성이 있어 확정 아님 | 상 | 제거 전 실제 LLM tool-call 이름을 런타임 로그로 트레이싱해 실사용 여부 확인 필요 |
| 8 | `interview.yaml:16,19` | 존재하지 않는 tool 이름 `search_place`를 호출하라고 지시(실제 바인딩된 이름은 `get_address_from_coords/keyword/category`) | 실제 구현과 맞지 않는 프롬프트 문구 | 하 | 프롬프트 문구를 실제 tool 이름으로 수정 |
| 9 | `extraction.yaml:8-25,54-70` | 존재하지 않는 `WalkMode` 값(`circular_child` 등)을 언급하나 `ModeTool`의 어떤 함수도 `mode` 인자를 받지 않아 생성 불가 | 실제 구현과 맞지 않는 프롬프트 문구 | 하 | 프롬프트 문구를 실제 `WalkMode` 3종만 언급하도록 수정 |

각 행은 코드 대조로 확인한 사실만 채우고, 확인하지 못한 항목은 빈 값 대신 "미확인"과 확인 방법을 적는다.

## 3. 조사 완료 기준

- 발견 목록의 모든 대상이 "현재 사실"과 "제거 근거"까지 채워진다.
- "미확인"으로 남은 항목이 없다. 남아 있다면 확인 방법과 함께 다음 조사 대상으로 표시한다.

## 4. 승인과 구현 완료 기준

- 팀이 발견 목록의 각 항목별 제거 여부를 승인한다.
- 승인된 항목만 별도 구현 작업 단위로 옮기고, 이 Proposal 문서는 승인 이력만 남긴다.
- 이 Proposal 자체는 코드를 변경하지 않으며, 구현은 승인 후 별도 커밋에서 진행한다.