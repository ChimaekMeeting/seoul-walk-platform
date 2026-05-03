from typing import Any
import json

class PromptUtils:
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
        
        # 딕셔너리나 리스트인 경우 JSON 문자열로 예쁘게 변환
        if isinstance(obj, (dict, list)):
            json_str = json.dumps(obj, ensure_ascii=False, indent=2)
            self.escape_braces(json_str)
        
        return self.escape_braces(str(obj))