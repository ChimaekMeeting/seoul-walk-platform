# 챗봇 에이전트

> 상태: Current  
> 기준일: 2026-07-27  
> 관련 코드: `src/agent/`, `src/service/chat/prewalk_service.py`, `src/schema/prewalk_schema.py`

이 문서는 챗봇 영역의 입구입니다. 상세 State·Node·Edge·Tool 계약은 [챗봇 Agent 하네스](agent_harness.md)에서 관리합니다.

## 현재 코드 위치

| 구성요소 | 위치 | 역할 |
|---|---|---|
| State | `src/schema/prewalk_schema.py` | 대화와 경로 생성에 필요한 공유 상태 |
| Graph 조립 | `src/service/chat/prewalk_service.py` | LangGraph Node 등록과 Edge·종료 조건 정의 |
| Node | `src/agent/nodes/` | 추출, 추가 질문, 경로 실행과 날씨 확인 |
| Tool | `src/agent/tools/` | 장소·모드·경로 기능 호출 |
| Prompt | `src/prompt/` | LLM 입력 템플릿 |
| 외부 API | `src/infrastructure/external/` | GPT·Kakao·날씨 API 연동 |
| 대화 상태 저장 | `src/infrastructure/cache/` | Valkey 기반 상태 저장 |

## 현재 실행 흐름

```text
사용자 입력
→ Extractor
→ Interviewer
→ 정보 부족: 질문 후 종료
→ 정보 충족: 확인 대기 후 종료
→ 다음 긍정 응답: RouteExecutor 직접 실행
→ 경로 결과 저장·반환
```

`WeatherChecker`는 현재 위 Graph의 Node가 아니라 초기 메시지를 만들 때 별도로 호출됩니다.

## 상세 문서

- [챗봇 Agent 하네스](agent_harness.md): 파일·State·Node·Edge·Tool 계약
- [챗봇 경로 추천 Workflow](../architecture/workflows/prewalk_conversation.md): API 실행·실패·검증 결과

## 미래 제안

- [챗봇 Agent 업그레이드 제안](../proposals/chatbot_upgrade_proposal.md): 구현 전 결정할 선택지와 독립 작업 단위
