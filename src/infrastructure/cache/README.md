# Cache Layer

## 1. 소개
- Valkey 세션에 대한 CRUD를 구현합니다.
- PostgreSQL DB에 대한 CRUD는 `src/repository`에서 구현합니다.
- 구조는 아래와 같습니다.
```
- valkey.py  <- 수정할 필요 X
- repository/
```

## 2. 코드 작성 규칙
- class로 작성합니다.

## 3. 명칭 규칙
- repository 내 파일명은 {기능}_repository.py로 통일합니다.

## 4. 주석 작성 규칙
- """\n~~~\n""" 형식에 맞게 작성합니다.