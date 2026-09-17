from typing import Any
import json
from pydantic import BaseModel
import re

class PydanticUtils:
    @staticmethod
    def dump(obj: Any) -> Any:
        if isinstance(obj, BaseModel):
            # mode="json": Enum(WalkMode 등)을 .value 문자열로, 그 외 JSON 비호환 타입도
            # JSON 네이티브 값으로 바꾼다. 중첩된 BaseModel(예: Location)도 함께 재귀 변환된다.
            return obj.model_dump(mode="json")
        elif isinstance(obj, list):
            return [PydanticUtils.dump(item) for item in obj]
        elif isinstance(obj, dict):
            return {key: PydanticUtils.dump(value) for key, value in obj.items()}
        return obj
        
class PromptUtils:
    _HTML_TAG_RE        = re.compile(r"<[^>]+>")
    _REPEATED_WORD_RE   = re.compile(r"\b(\S{1,20})(?:\s+\1\b){2,}")   # 같은 단어가 공백으로 총 3회+ 반복
    _REPEATED_CHUNK_RE  = re.compile(r"(.{1,20}?)\1{2,}")              # 같은 문자열(문자 1개 포함)이 붙어서 총 3회+ 반복
    _WHITESPACE_RUN_RE  = re.compile(r"\s+")

    @staticmethod
    def sanitize_user_prompt(text: str) -> str:
        """
        프롬프트를 정규화합니다.
        - HTML 태그 제거
        - 과도한 공백 축소
        - 반복 문자 및 문자열 축약
        """
        if not text:
            return text
        text = PromptUtils._HTML_TAG_RE.sub(" ", text)
        text = PromptUtils._REPEATED_WORD_RE.sub(lambda m: f"{m.group(1)} {m.group(1)}", text)
        text = PromptUtils._REPEATED_CHUNK_RE.sub(lambda m: m.group(1) * 2, text)
        text = PromptUtils._WHITESPACE_RUN_RE.sub(" ", text).strip()
        return text

    @staticmethod
    def escape_braces(text: str) -> str:
        """
        단순히 텍스트의 중괄호만 이스케이프 처리합니다.
        """
        if not text:
            return ""
        return text.replace("{", "{{").replace("}", "}}")
    
    def format_for_prompt(self, obj: Any) -> str:
        """
        데이터 객체를 프롬프트 주입용 문자열로 변환합니다.
        - None 또는 빈 값 처리
        - LangChain PromptTemplate 에러 방지를 위한 중괄호 이스케이프({{, }})
        - 한글 깨짐 방지 (ensure_ascii=False)
        """
        if obj is None or obj == "" or obj == []:
            return "없음"
        
        # pydantic 객체인 경우
        obj = PydanticUtils.dump(obj)

        # 딕셔너리나 리스트인 경우 JSON 문자열로 예쁘게 변환
        if isinstance(obj, (dict, list)):
            json_str = json.dumps(obj, ensure_ascii=False, indent=2)
            return self.escape_braces(json_str)

        return self.escape_braces(str(obj))