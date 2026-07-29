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

- 하드코딩된 문자열 분리 — [하드코딩 문구 처리 방안 제안](../proposals/chatbot_hardcoding_proposal.md)에서 별도로 다룬다
- `frontend/**`
- 이 문서만으로 승인되지 않은 코드 변경

## 2. 발견 목록

| ID | 대상 | 현재 사실 | 제거 근거 | 리스크(상/중/하) | 상태 | 후속 조치 |
|---|---|---|---|---|---|---|
| 1 | `src/prompt/complete.yaml` | `prompt_name="complete"` 호출부가 `src/` 전체에 0건이었음(`route_executor.py:64` 주석에만 언급) | 어디서도 로드·호출되지 않는 프롬프트 파일 | 하 | **완료** | 파일 삭제함. `chatbot_upgrade_proposal.md` P7 실행 시 재확인 |
| 2 | `src/prompt/route_result.yaml`, `route_executor.py:65-73`(주석 블록) | 호출 코드가 전부 주석 처리되어 있고 활성 호출부 없음 | 런타임에 도달 불가능한 죽은 프롬프트·코드 | 중 | **완료** | 파일 삭제, 주석 블록 제거함 |
| 3 | `PrewalkOrchestrator._build_graph`의 `route_executor` 노드 등록·조건부 엣지(`prewalk_service.py:69,75-80`) | `Interviewer.run`은 `is_complete=True`를 만들지 않음(`interviewer.py:52,96,118` 모두 `False`) → `self.graph.ainvoke` 경로에서 `route_executor`에 도달 불가. 실제 실행은 `orchestrator()`의 수동 우회(`prewalk_service.py:181`)뿐 | Graph 선언과 실제 실행 경로가 불일치하는 배선 | 중 | **보류** | 경로 생성 자체는 필요하므로 노드·엣지 배선은 현행 유지로 결정. `chatbot_upgrade_proposal.md` D1 결정 전까지 손대지 않음 |
| 4 | `Interviewer.run`의 `raw_response.content`(`interviewer.py:59-116`) | `candidates`가 채워지면(LLM의 `tool_calls`뿐 아니라 `_execute_tool_calls` 섹션 2의 자동 보완도 트리거) `raw_response.content`는 최종 응답에 반영되지 않고 `_build_confirmation_message` 또는 `interview.yaml` 재호출(도구 미바인딩) 응답으로 대체됨 | LLM 호출 결과 중 일부가 다른 응답에 가려져 사용되지 않는 경우(범위 2번 항목) | 하 | **결정 완료(현행 유지)** | tool 호출 여부는 매 호출마다 LLM이 동적으로 판단(`tool_choice=auto`)하므로 사전에 출력 구조를 분기하면 오히려 일관성이 떨어짐. 버려지는 `.content`는 검색 결과 확정 전 생성된 것이라 애초에 최신 정보를 반영할 수 없어 대체가 타당함. 개선 불필요로 결론(대체 메커니즘은 10번 항목으로 `location_formatter.yaml` 대신 `interview.yaml` 재호출로 변경됨) |
| 5 | `State.weather_data`(`prewalk_schema.py:68`) | 쓰기 1건(`prewalk_service.py:130`)만 있고 `src/` 전체에서 읽는 코드 없음 | write-only 필드 | 중 | **완료** | 필드 삭제, `weather_checker.py`·`prewalk_schema.py`의 미사용 `EnvironmentInfo` import도 함께 제거함 |
| 6 | `BasePreference.purpose`(`prewalk_schema.py:24`) | 유일한 쓰기(`extractor.py:82`)가 이전 턴 값을 그대로 복사만 하고, 어떤 Tool도 `purpose` 인자를 받지 않아 항상 `None` | 실질적으로 항상 null인 필드 | 중 | **완료** | 필드, `extractor.py:82` 복사 코드, `interview.yaml:33`(따뜻한 문맥 추론 규칙) 전부 제거함 |
| 7 | `PlaceTool.get_address_from_coords`/`get_address_from_category`(`place_tools.py`) | 담당자 확인 결과 `get_address_from_coords`는 현재 위치 파악용으로 만들었으나 `prewalk_service.py:111`에서 `KakaoClient`를 직접 호출하는 경로가 이미 그 역할을 수행 중이라 중복. `get_address_from_category`는 카테고리(카페·서점 등) 검색용으로 의도됐으나 `interview.yaml`에 관련 지침이 없어 LLM이 호출할 근거가 없었음 | `get_address_from_coords`는 이미 다른 경로로 처리되는 기능의 중복, `get_address_from_category`는 기능 자체는 필요하나 프롬프트 연결이 누락됨 | 하 | **완료** | `get_address_from_coords`는 `place_tools.py`에서 제거(미사용 `PlaceInfo` import 포함). `get_address_from_category`는 제거 대신 `interview.yaml`에 카테고리 검색 지침을 추가해 기능을 연결함 |
| 8 | `interview.yaml:16,19` | 존재하지 않는 tool 이름 `search_place`를 호출하라고 지시(실제 바인딩된 이름은 `get_address_from_coords/keyword/category`) | 실제 구현과 맞지 않는 프롬프트 문구 | 하 | **완료** | 프롬프트 문구를 실제 tool 이름(`get_address_from_keyword`)으로 수정함 |
| 9 | `extraction.yaml:8-25,54-70` | 존재하지 않는 `WalkMode` 값(`circular_child` 등)을 언급하나 `ModeTool`의 어떤 함수도 `mode` 인자를 받지 않아 생성 불가 | 실제 구현과 맞지 않는 프롬프트 문구 | 하 | **완료** | 프롬프트 문구·판단 예시의 `mode=` kwarg를 실제 `WalkMode` 3종 기준으로 정리함 |
| 10 | `extraction.yaml`의 `origin_candidates`/`destination_candidates`, `extractor.py:29-30`, `location_formatter.yaml` 전체 | `interviewer.py:79,86`는 검색 결과 중 항상 `candidates[...][0]`을 확정하고, 후보 리스트는 사용자가 다음 턴에 다른 후보를 지목해 정정할 때만 재사용됨. 팀 합의로 항상 첫 번째 후보만 쓰고 정정 절차를 없애기로 함 | 정정 기능을 없애기로 합의해 후보 재선택 관련 입력·프롬프트 문구가 불필요해짐 | 중 | **완료** | `extraction.yaml`·`extractor.py`에서 후보 관련 문구·코드 제거. `location_formatter.yaml`은 별도 프롬프트로 남기지 않고 완전히 삭제, 그 역할(검색 결과 반영 응답 생성)을 `interview.yaml` 재호출(도구 미바인딩 `parser=self.str_parser`)로 흡수함. 이 과정에서 `_get_missing_info`가 좌표(lat/lon)까지 확인하도록 `_has_location` 기준으로 수정해, 부분 검색 실패(예: destination만 결과 없음) 시에도 재계산된 `missing_info`가 정확히 남은 항목을 반영하도록 함 |

| 11 | `RouteExecutor(GPTClient)` 상속, `self.prompt_utils`/`self.str_parser`(`route_executor.py`) | `route_result.yaml` 호출(2번 항목)이 이미 제거되어 `RouteExecutor`엔 LLM 호출이 전혀 없음. `self.llm`/`get_response`/`prompt_utils`/`str_parser` 참조가 `route_executor.py` 전체에 0건(초기화만 되고 미사용) | GPTClient 상속과 그 하위 객체들이 전부 죽은 초기화 코드 | 하 | **완료** | `GPTClient` 상속 제거(`class RouteExecutor:`로 변경), `PromptUtils`/`StrOutputParser` import·초기화 제거. `RouteExecutor()` 생성 방식(`dependencies.py:51`)은 인자 없이 호출해 영향 없음 |

각 행은 코드 대조로 확인한 사실만 채우고, 확인하지 못한 항목은 빈 값 대신 "미확인"과 확인 방법을 적는다. "상태"는 완료/부분 완료/보류/미착수로 표기하고, 코드 변경이 있었으면 후속 조치 칸에 실제로 한 일을 기록한다.

## 3. 조사 완료 기준

- 발견 목록의 모든 대상이 "현재 사실"과 "제거 근거"까지 채워진다.
- "미확인"으로 남은 항목이 없다. 남아 있다면 확인 방법과 함께 다음 조사 대상으로 표시한다.

## 4. 승인과 구현 완료 기준

- 팀이 발견 목록의 각 항목별 제거 여부를 승인한다.
- 승인된 항목만 별도 구현 작업 단위로 옮기고, 이 Proposal 문서는 승인 이력만 남긴다.
- 이 Proposal 자체는 코드를 변경하지 않으며, 구현은 승인 후 별도 커밋에서 진행한다.