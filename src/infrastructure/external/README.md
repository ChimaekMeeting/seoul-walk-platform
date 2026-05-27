# External API Clients

## 1. 소개
- 외부 API와의 통신을 담당합니다.

## 2. 구조
```
client/
schema/
```
- client: 외부 API와 직접적인 통신을 담당합니다.
- schema: 외부 API를 통해 가져올 데이터 구조를 정의합니다.

## 3. 파일 명명 규칙
- client/: {기능}_client.py
- schema/: {기능}_schema.py

## 4. client 작성 규칙
- 클래스로 작성합니다.
- 주석은 """\n~~\n""" 형식을 준수합니다.

## 5. schema 작성 규칙
- 기본적으로 BaseModel을 상속받는 클래스로 작성합니다. BaseModel은 데이터 구조가 깨지는 것을 방지합니다.
- 주석은 """\n~~\n""" 형식을 준수합니다.