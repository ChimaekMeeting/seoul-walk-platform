# Agent Layer

## 1. 소개
- LLM 기반 산책 경로 추천 챗봇 에이전트를 구현합니다.
- 구조는 아래와 같습니다.
```
nodes/
tools/
utils/
```
- `nodes/`: 에이전트 그래프의 각 처리 단계를 담당합니다.
- `tools/`: LangChain `StructuredTool`로 래핑된 외부 API 호출 도구를 정의합니다.
- `utils/`: 프롬프트 전처리 등 공통 유틸리티를 제공합니다.

## 2. 코드 작성 규칙
- 클래스로 작성합니다.
- `nodes/`의 각 노드는 `async def run(self, state: State) -> State` 시그니처를 따릅니다.
- `GPTClient`를 상속하는 노드는 `super().get_response()`를 통해 LLM을 호출합니다.
- 주석은 `"""\n~~\n"""` 형식을 준수합니다.

## 3. 파일 명명 규칙
- `nodes/`: `{기능}.py`
- `tools/`: `{기능}_tool.py`
- `utils/`: `{기능}_utils.py`

## 4. 주석 작성 규칙
- 주석은 `"""\n~~\n"""` 형식을 준수합니다.
