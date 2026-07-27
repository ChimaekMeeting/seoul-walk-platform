# 챗봇 Agent 하네스 감사 판정

> 기준일: 2026-07-27  
> 대상: `docs/chatbot/agent_harness.md`  
> 근거: Claude Code 코드 대조 결과, 현재 코드 재확인, Git 이력

## 목적

외부 코드 대조 감사에서 제기된 항목을 그대로 반영하지 않고, 현재 코드와 저장소 이력으로 다시 판정한다. 승인된 사실만 Current 문서에 반영하고 미래 변경안은 Proposal로 분리한다.

## 판정

| ID | 판정 | 근거 | Current 반영 |
|---|---|---|---|
| F1 | 부분 수용 | TTL 3,600초는 `ChatStateRepository.save_state` 코드와 실행으로 확인됐다. 경로 좌표 수·거리는 격리 실행에서 관측했지만 저장소 안의 자동 재현 아티팩트는 없다. RouteHistory ID는 실행 환경에 종속된다. | ID를 제거하고 좌표 수·거리를 2026-07-27 일회성 관측값으로 명시했다. |
| F2 | 출처 보강 후 유지 | `0ed8073b`에서 `Interviewer`의 `is_complete`에 따라 `RouteExecutor`로 가는 조건부 Edge가 추가됐다. `e42c36d`에서 확인 대기와 긍정 턴의 직접 실행이 추가됐다. | 역사 서술을 Git 이력 기준으로 바꾸고 두 커밋을 명시했다. |
| F3 | 수용 | 현재 실행 설명이 바로 앞 문단과 일부 중복되고, Graph 안팎의 미래 선택은 Current 문서 범위를 벗어난다. | 중복을 줄이고 미래 결정 문장을 제거했다. |
| F4 | 수용 | `WeatherChecker.run`은 `(EnvironmentInfo, str)`을 반환하고, `State.weather_data` 대입은 `PrewalkOrchestrator.get_init_message`에서 수행한다. | 최초 작성자를 `Orchestrator init`으로 수정했다. |

## 특별 확인 항목

감사에서 이상 없음으로 판정한 다음 사실은 현재 코드와 일치하므로 문서 표현을 유지했다.

- 현재 `Interviewer`는 `is_complete=True`를 만들지 않아 Graph의 `RouteExecutor` Edge에 도달하지 않는다.
- 긍정 확인 턴은 `graph.ainvoke`가 아니라 Orchestrator의 `route_executor.run`을 사용한다.
- intent State의 `access_token`은 전체 State 저장과 API 응답에 포함된다.
- `ChatSession.current_state`는 경로 완료 후에도 `START`다.
- `complete.yaml`과 `route_result.yaml`은 현재 실행에서 사용하지 않는다.
- 기존 API 테스트는 Orchestrator를 mock하며 실제 Node·Edge·LLM Tool 호출을 검증하지 않는다.

## 결론

위 판정을 반영한 `docs/chatbot/agent_harness.md`를 현재 구현 계약으로 사용한다. 업그레이드 방향과 선택지는 `docs/proposals/chatbot_upgrade_proposal.md`에서 별도로 관리한다.
