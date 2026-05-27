# Schema Layer

## 1. 소개
- BE 서버 내부에서 사용하는 schema를 정의합니다.
- FE와 통신할 때 사용하는 schema는 `interfaces/schema/`에 정의합니다.
- 외부 API와 통신할 때 사용하는 schema는 `infrastructure/external/schema/`에 정의합니다.

## 2. 코드 작성 규칙
- 기본적으로 BaseModel을 상속받는 클래스로 작성합니다. BaseModel은 데이터 구조가 깨지는 것을 방지합니다.

## 3. 명칭 규칙
- 파일명은 {기능}_schema.py로 통일합니다.

## 4. 주석 작성 규칙
- """\n~~~\n""" 형식에 맞게 작성합니다.