# 데이터 적재 가이드

## 목적

다운로드 폴더에 받은 공공데이터 원본을 프로젝트가 읽는 위치인 `src/data/raw`로 옮긴 뒤, 기존 raw 적재기와 도메인 collector를 순서대로 실행합니다.

원본 CSV/XLSX 파일은 `.gitignore`에 의해 커밋되지 않습니다. 각 개발자는 같은 파일명을 유지한 채 로컬에서 준비해야 합니다.

## 1. 원본 파일 준비

다운로드 폴더에 아래 파일이 있는지 확인합니다.

- `전국어린이보호구역표준데이터.csv`
- `전국스마트가로등표준데이터.csv`
- `전국자전거도로표준데이터.csv`
- `서울시CCTV정보.xlsx`
- `서울시 주요 공원현황.csv` 또는 `서울시_주요_공원현황.csv`
- `서울시 자치구별 도보 네트워크 공간정보.csv` 또는 `서울시_자치구별_도보_네트워크_공간정보.csv`

파일을 `src/data/raw`로 복사합니다.

```bash
poetry run python scripts/stage_raw_data.py
```

이미 복사된 파일을 최신 다운로드 파일로 덮어쓰려면 다음처럼 실행합니다.

```bash
poetry run python scripts/stage_raw_data.py --overwrite
```

## 2. DB 테이블 생성

먼저 DB 컨테이너가 실행 중인지 확인합니다.

```bash
docker-compose up -d
```

```bash
poetry run python -c "from src.entity.base import init_db; init_db()"
```

주의: `poetry run python -m src.main`은 FastAPI 서버를 실행하고 종료되지 않습니다.
테이블 생성만 재현하려면 위의 `init_db()` 원샷 명령을 사용합니다.

DB 연결에서 `127.0.0.1:5434 connection refused`가 발생하면 DB 컨테이너가 내려간 상태입니다.
이때는 `docker-compose up -d`로 컨테이너만 다시 시작하고, 기존 적재 데이터를 보존해야 한다면 `docker-compose down -v`는 사용하지 않습니다.

## 3. Raw 데이터 적재

```bash
poetry run python -m src.data.source_collector
```

이 단계에서 `OSMSource`, `KakaoSource`, `PublicSource`, `CSVSource`가 raw 테이블을 채웁니다. 다운로드한 CSV/XLSX 파일은 `CSVSource`가 읽습니다.

공공데이터 API 주의사항:

- `PUBLIC_DATA_API_KEY`는 어린이놀이시설 API와 TourAPI 활용신청이 모두 승인된 data.go.kr 서비스키여야 합니다.
- 어린이놀이시설 API 권한이 없으면 `PublicSource`의 `play_facility` 단계에서 `403 Forbidden`이 발생하고, 이후 Public/CSV 적재가 중단될 수 있습니다.
- 실패 후 같은 DB에서 재실행하면 이미 저장된 OSM/Kakao raw는 repository의 `exists(query_key)` 검사로 대부분 스킵됩니다. 시간이 오래 걸린 적재를 보존하려면 DB를 초기화하지 말고 `source_collector`부터 다시 실행합니다.

## 4. 서비스용 도메인 데이터 적재

```bash
poetry run python -m src.data.data_collector
```

이 단계에서 raw 데이터를 기반으로 안전, 어린이 시설, 랜드마크, 자연, 도보 네트워크 등 서비스에서 직접 쓰는 레이어와 네트워크 데이터를 구성합니다.

### 4-1. 위 명령으로 실제 반영되는 데이터

`data_collector.py`에서 현재 주석 없이 호출되는 collector만 실제로 DB에 반영됩니다.

| collector | layer | score |
|---|---|---|
| `BaseNetworkCollector` | walk_nodes / walk_edges | 없음 |
| `NatureCollector` | nature_layer | nature_score (OSM 녹지 기반) |
| `SafetyCollector` | safety_layer | safety_score |
| `ChildCollector` | child_layer | child_score |
| `SeoulBoundaryCollector` | - | - |
| `SeoulWaterCollector` | - | - |
| `LandmarkCollector` | landmark_layer | landmark_score |

### 4-2. approved=true이지만 현재 비활성인 데이터

`src/data/registry.yaml`에는 `approved: true`로 등록되어 있지만, `data_collector.py`에서 호출이 주석 처리되어 있어 위 명령을 실행해도 반영되지 않는 collector입니다.

```python
# src/data/data_collector.py
# print("--- 경사로 적재 ---")
# SlopeCalculator().save()
...
# print("--- 러닝 데이터 적재 ---")
# RunningCourseCollector().save()
```

| collector | layer | score | 관련 raw 파일 |
|---|---|---|---|
| `RunningCourseCollector` | running_layer | running_score | 서울시 주요 공원현황.csv, 전국자전거도로표준데이터.csv, 서울시 하천.geojson |
| `SlopeCalculator` | - | slope_score | (raw 파일과 직접 연결된 근거 없음) |

이 PR에서는 위 주석을 해제하지 않습니다. 활성화 여부는 팀 확인 후 별도로 진행합니다. 자세한 연결 상태는 `docs/score_data_catalog.md`를 참고하세요.

### 4-3. draft/undecided 상태라 반영하지 않는 데이터

`src/data/registry.yaml`에서 `approved: false`인 dataset은 raw 파일이 `src/data/raw`에 있어도 위 3단계 명령으로 적재되지 않습니다.

| 파일 | registry dataset_key | 상태 |
|---|---|---|
| 전국가로수길정보표준데이터.csv | `street_tree` | draft — `nature_score` 후보, collector 미구현. 본 적재 흐름에 포함되지 않음 |
| 서울 둘레길.csv | `seoul_trail` | draft — layer/score/collector 모두 `undecided`. CSV에는 좌표 컬럼이 없고, `RunningCourseCollector`는 `_TRAIL_COORDS` 하드코딩 좌표로 trail geometry를 생성 중 |

이 두 파일은 `src/data/intake/inspect_dataset.py` / `draft_dataset.py`로 검수 기록만 남길 수 있고, `approved: true`로 전환되기 전까지는 `source_collector`/`data_collector` 어디에도 포함되지 않습니다. 전체 연결 상태 표는 `docs/score_data_catalog.md`를 참고하세요.

## AI 응답 제한 방향

AI가 없는 정보를 만들지 않게 하려면 프롬프트만으로 막기보다 아래 흐름을 지키는 것이 좋습니다.

- DB/route engine/tool 결과를 먼저 계산합니다.
- LLM에는 계산 결과와 사용자 조건만 전달합니다.
- 프롬프트에는 제공된 데이터 밖의 장소, 수치, 시설 정보를 추측하지 말라고 명시합니다.
- 결과 객체에 없는 값은 "확인된 정보 없음"처럼 표현하도록 합니다.

즉, AI는 경로와 데이터를 결정하는 주체가 아니라, 이미 검증된 결과를 사용자에게 자연어로 설명하는 역할에 가깝게 두는 것이 안전합니다.

## 신규 데이터 확장

새 데이터가 계속 추가되는 경우에는 단순히 raw에 적재하는 것만으로 끝내지 않습니다. layer, score, profile, scoring engine 반영 기준까지 함께 확인해야 합니다.

자세한 작업 범위와 PR 분할 계획은 `docs/data_pipeline_expansion_plan.md`를 참고합니다.
