# Data Layer

## 1. 소개
- 데이터를 수집합니다.
```
- /collectors
- /raw
- /utils
- data_collector.py
```

## 2. 코드 작성 규칙
- class로 작성합니다.
- collector.save()만 호출하면 데이터 적재가 가능하도록 코드를 작성합니다.
- save() 메서드는 반드시 아래의 형식대로 작성합니다.
```
def save(self) -> None:
    """
    데이터를 적재합니다.
    """
    self.update_node()
    self.update_edge()
```
- DB에 직접 접근할 수 없습니다. Repository를 통해 DB에 간접적으로 접근해야 합니다.

## 3. 파일 명명 규칙
- collectors 내 파일명은 {기능}_collector.py로 통일합니다.
- utils 내 파일명은 {기능}_utils.py로 통일합니다.

## 4. 주석 작성 규칙
- """\n~~~\n""" 형식에 맞게 작성합니다.

## 5. 꿀팁
- 작성한 collector를 data_collector.py에서 호출하면 `python -m src.data.data_collector` 한 줄의 명령어로 모든 데이터를 적재할 수 있습니다.