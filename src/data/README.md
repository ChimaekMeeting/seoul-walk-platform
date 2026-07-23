# Data Layer

## 1. 소개
- 데이터를 수집합니다.
- 도보 네트워크 필드와 적재 기준은 `docs/data/walk_network_contract.md`를 기준으로 합니다.
- 원본별 역할과 V1 사용 상태는 `docs/data/dataset_roles.md`에서 관리합니다.
```
- /collectors
- /raw
- /utils
- data_collector.py
```

## 2. 코드 작성 규칙
- class로 작성합니다.
- 일반 collector는 `collector.save()`로 적재합니다.
- 기준 도보 네트워크는 저장 의도가 명확하도록 `upsert()`와 `rebuild()`를 구분합니다.
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

### 도보 네트워크 저장 모드

- `BaseNetworkCollector.upsert()`: 기존 score를 보존하면서 NODE·LINK 원본 기반 필드를 추가·갱신합니다. 원본에서 사라진 ID는 삭제하지 않습니다.
- `BaseNetworkCollector.rebuild()`: `walk_edges`, `walk_nodes`를 최신 원본 전체로 교체합니다. score가 초기화되므로 활성 Layer collector를 이어서 실행해야 합니다.
- 실제 SQL과 트랜잭션은 `NetworkWriteRepository`가 담당합니다.
- `data_collector.py`는 어느 모드든 네트워크 적재 후 활성 Layer와 score 단계를 이어서 실행합니다.

## 3. 파일 명명 규칙
- collectors 내 파일명은 {기능}_collector.py로 통일합니다.
- utils 내 파일명은 {기능}_utils.py로 통일합니다.

## 4. 주석 작성 규칙
- """\n~~~\n""" 형식에 맞게 작성합니다.

## 5. 꿀팁
- 작성한 collector를 data_collector.py에서 호출하면 `python -m src.data.data_collector` 한 줄의 명령어로 모든 데이터를 적재할 수 있습니다.

## 6. 로컬 원본 데이터 준비
- 다운로드 폴더에 받은 CSV/XLSX 원본은 `scripts/stage_raw_data.py`로 `src/data/raw`에 복사합니다.
```
poetry run python scripts/stage_raw_data.py
poetry run python -m src.data.source_collector
poetry run python -m src.data.data_collector
```
- 자세한 순서는 `docs/data_ingestion_runbook.md`를 참고합니다.
