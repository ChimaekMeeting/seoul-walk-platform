# Result (Builder)

**목적:** Route engine 내부 탐색 결과를 앱/백엔드가 사용하기 쉬운 표준 `RouteResult` DTO 형태로 조립합니다.

**금지사항:**
- 최종 자연어 문장 생성은 LLM Agent 책임이므로 여기서 작성하지 않습니다.
- 여기서는 route 결과에 필요한 구조화된 데이터(JSON 포맷)만 만듭니다.
