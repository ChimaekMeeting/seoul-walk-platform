# entity Layer

## 1. 소개
- DB의 table과 1 대 1로 매핑됩니다.
- 구조는 아래와 같습니다.
```
- base.py
- user.py
- chat_session.py
- layer/
- network/
```
- entity의 크기가 커진다면, 파일을 더 세분화할 수 있습니다.

## 2. entity 작성 규칙
- 한 파일 내 class 1개만을 작성하는 것을 원칙으로 하되, 자식 class 혹은 Enum class는 같은 파일에 작성하는 것을 허락합니다.
- Base를 상속받는 class 형태로 작성합니다.

## 3. 명명 규칙
- layer 내 파일명은 {기능}_layer.py로 통일합니다.

## 4. 주석 작성 규칙
- """\n~~~\n""" 형식에 맞게 작성합니다.

## 5. 주의사항
- entity를 구현한 후, `base.py`의 `register_entities()`에 추가하고 `python -m src.main.py`를 실행해야 DB에 실제 테이블이 생성됩니다.

## 6. 고민할 부분
- layer를 쌓을 때마다 edge에 새로운 컬럼을 추가해야 함. 이를 해결할 방법은..?