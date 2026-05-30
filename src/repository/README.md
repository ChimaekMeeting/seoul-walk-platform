# Repository Layer

## 1. 소개
- PostgreSQL DB에 대한 CRUD 기능을 구현합니다.
- Valkey Session에 대한 CRUD 기능은 `infrastructure/cache/repository`에 구현합니다.
- 구조는 아래와 같습니다.
```
chat/
layer/
network/
user/
utils.py
```
- 추후 repository가 더 늘어나는 경우, 디렉토리를 세분화해도 됩니다.
- utils.py에는 repository의 공통 모듈을 작성합니다.

## 2. 코드 작성 규칙
- 한 파일에 한 개의 class만을 작성합니다.
- SQL문법이 아닌 ORM 기반 문법으로 코드를 작성합니다.

## 3. 파일 명명 규칙
- api 내 파일명은 {기능}_repository.py로 통일합니다.

## 4. 주석 작성 규칙
- """\n~~~\n""" 형식에 맞게 작성합니다.