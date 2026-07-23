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
- `BaseNetworkCollector.rebuild()`: `walk_edges`, `walk_nodes`를 최신 원본 전체로 교체합니다. score가 초기화되므로 선택한 scope의 후속 Collector만 이어서 실행합니다.
- 실제 SQL과 트랜잭션은 `NetworkWriteRepository`가 담당합니다.
- `data_collector.py`의 기본 `v1` 범위는 네트워크와 좌표 검증용 서울 경계·수계만 실행합니다.
- 기존 전체 Layer·score 파이프라인은 `--scope legacy-all`을 명시한 경우에만 실행합니다.

## 3. 파일 명명 규칙
- collectors 내 파일명은 {기능}_collector.py로 통일합니다.
- utils 내 파일명은 {기능}_utils.py로 통일합니다.

## 4. 주석 작성 규칙
- """\n~~~\n""" 형식에 맞게 작성합니다.

## 5. 실행 범위

- `--scope v1`은 승인된 V1 데이터만 실행하며 기본값입니다.
- `--scope legacy-all`은 기존 전체 Collector를 명시적으로 실행합니다.
- 신규 Collector는 승인 후 `collect_v1()`에 추가합니다.
- 현재 V1은 도보 네트워크, 공원 Polygon, 서울 경계, 수계를 실행합니다.
- 공원 Polygon은 `nature_layer`에 보존하고, 각 WalkEdge 길이 중 Polygon 내부 비율을 `park_overlap_ratio`에 저장합니다.
- 도보망 원본 `raw_is_park_green`은 그대로 유지하며, `ParkPolygonCollector`는 `nature_score`를 갱신하지 않습니다.
- `raw_is_park_green`과 `park_overlap_ratio`를 `nature_score`로 결합하는 정책은 별도로 확정합니다.

## 6. 로컬 원본 데이터 준비
- 다운로드 폴더에 받은 CSV/XLSX 원본은 `scripts/stage_raw_data.py`로 `src/data/raw`에 복사합니다.
```
poetry run python scripts/stage_raw_data.py
poetry run python -m src.data.source_collector --scope v1
poetry run python -m src.data.data_collector --scope v1 --network-mode upsert
```
- 현재 V1 원본은 로컬 파일을 각 Collector가 직접 읽으므로 `source_collector --scope v1`은 외부 RAW를 적재하지 않습니다.
- 자세한 순서는 `docs/data_ingestion_runbook.md`를 참고합니다.
