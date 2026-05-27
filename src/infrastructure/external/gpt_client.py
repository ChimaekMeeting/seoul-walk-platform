from typing import Any

def request_llm_response(prompt_name: str, variables: dict[str, Any]) -> dict[str, Any]:
    """
    LLM/GPT 호출 예정 함수.
    agent/application은 이 함수의 구현에 직접 의존하지 않고, 추후 adapter 형태로 사용한다.

    담당:
    - prompt_name과 variables를 받아 LLM provider에 전달할 예정
    - raw LLM response 또는 structured response를 반환할 예정

    금지:
    - 현재 단계에서 openai/langchain 등 실제 provider import 금지
    - route_engine 내부에서 이 함수를 직접 호출하는 구조 금지

    TODO:
    - prompt registry 위치를 prompts/로 둘지 agent/ 내부로 둘지 정한다.
    - structured output parsing 책임을 agent/application 중 어디에 둘지 정한다.
    """
    pass
