# 데이터 적재 실행 가이드
## 목적

다운로드 폴더에 받은 공공데이터 원본을 프로젝트가 읽는 위치인 `src/data/raw`로 옮긴 뒤, 기존 raw 적재기와 도메인 collector를 순서대로 실행합니다.

원본 CSV/XLSX 파일은 `.gitignore`에 의해 커밋되지 않습니다. 각 개발자는 같은 파일명을 유지한 채 로컬에서 준비해야 합니다.

## 1. 원본 파일 준비

`src/data/raw`에 아래 파일이 있는지 확인합니다. 없으면 공공데이터포털에서 직접 다운로드한 뒤 해당 폴더에 넣습니다.

| 파일명 | 출처 | CSVSource 태그 |
|---|---|---|
| `전국어린이보호구역표준데이터.csv` | 공공데이터포털 | `protection_zone` |
| `전국스마트가로등표준데이터.csv` | 공공데이터포털 | `streetlight` |
| `전국자전거도로표준데이터.csv` | 공공데이터포털 | `bike_road` |
| `서울시_자전거도로.csv` | 서울 열린데이터광장 | `bike_road_seoul` |
| `서울시CCTV정보.xlsx` | 서울 열린데이터광장 | `cctv` |
| `서울시 주요 공원현황.csv` | 서울 열린데이터광장 | `running_park` |
| `전국가로수길정보표준데이터.csv` | 공공데이터포털 | `street_tree` |
| `서울 둘레길.csv` | 서울 열린데이터광장 | `seoul_trail` |
| `공중화장실정보_서울특별시.csv` | 서울 열린데이터광장 | `toilet` |
| `서울시 버스정류소 위치정보.csv` | 서울 열린데이터광장 | `bus_stop` |
| `소상공인시장진흥공단_상가(상권)정보_서울_202603.csv` | 소상공인시장진흥공단 | `commercial` |
| `서울시 자치구별 도보 네트워크 공간정보.csv` | 서울 열린데이터광장 | (walk_network) |
| `서울시 하천.geojson` | 서울 열린데이터광장 | (river) |

> **주의:** 전국 데이터(`전국*` 파일)는 적재 시 서울 데이터만 필터링됩니다. 필터 기준은 `CSVSource.clean()` 내 `city_col` 설정을 따릅니다.

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

현재 V1 원본인 도보 네트워크 CSV와 공원 Shapefile은 각 Collector가 로컬 파일을 직접 읽습니다. 기본 V1 범위에서는 OSM·Kakao·공공 API·보조 CSV를 raw 테이블에 자동 적재하지 않습니다.

```bash
poetry run python -m src.data.source_collector --scope v1
```

기존 전체 RAW 수집은 아래처럼 명시한 경우에만 실행합니다.

```bash
poetry run python -m src.data.source_collector --scope legacy-all
```

`legacy-all`에서는 `OSMSource`, `KakaoSource`, `PublicSource`, `CSVSource`가 raw 테이블을 채웁니다. 다운로드한 CSV/XLSX 파일은 `CSVSource`가 읽습니다.

공공데이터 API 주의사항:

- `PUBLIC_DATA_API_KEY`는 어린이놀이시설 API와 TourAPI 활용신청이 모두 승인된 data.go.kr 서비스키여야 합니다.
- 어린이놀이시설 API 권한이 없으면 `PublicSource`의 `play_facility` 단계에서 `403 Forbidden`이 발생하고, 이후 Public/CSV 적재가 중단될 수 있습니다.
- 실패 후 같은 DB에서 재실행하면 이미 저장된 OSM/Kakao raw는 repository의 `exists(query_key)` 검사로 대부분 스킵됩니다. 시간이 오래 걸린 적재를 보존하려면 DB를 초기화하지 말고 `source_collector`부터 다시 실행합니다.

## 4. 서비스용 도메인 데이터 적재

개발 중 기존 네트워크를 지우지 않고 NODE·LINK를 갱신하려면 `upsert`를 사용합니다.

```bash
poetry run python -m src.data.data_collector --scope v1 --network-mode upsert
```

V1 기준 확정 후 기존 네트워크를 제거하고 최신 원본 전체로 교체하려면 `rebuild`를 사용합니다.

```bash
poetry run python -m src.data.data_collector --scope v1 --network-mode rebuild
```

기본 `v1` 범위는 도보 네트워크, 공원 Polygon 중첩 근거와 좌표 검증용 서울 경계·수계를 구성합니다. 공원 Polygon은 `park_overlap_ratio`만 갱신하며, 기존 안전·어린이·랜드마크·자연·러닝 score는 자동 실행하지 않습니다.

기존 전체 파이프라인은 `--scope legacy-all`을 명시한 경우에만 실행합니다.

### 4-0. 네트워크 적재 모드

| 모드 | 기존 NODE·LINK | 원본에서 사라진 ID | 기존 score | 사용 시점 |
|---|---|---|---|---|
| `upsert` | 동일 ID 갱신, 신규 ID 추가 | 유지 | 기존 값 보존 | 개발 중 필드·매핑 검증 |
| `rebuild` | 전체 삭제 후 재생성 | 제거 | 0으로 초기화, 선택한 scope의 후속 Collector만 실행 | V1 기준 확정 후 최종 검증 |

`rebuild`는 Docker volume이나 raw 테이블을 삭제하지 않습니다. `walk_edges`를 먼저 삭제하고 `walk_nodes`를 삭제한 뒤, 반대 순서로 최신 원본을 적재합니다.

두 모드 모두 실행 전에 `init_db()`로 새 엔티티 컬럼이 DB에 반영되어 있어야 합니다. `rebuild` 실행이 중간에 실패하면 네트워크 삭제와 삽입 전체가 하나의 트랜잭션으로 롤백됩니다.

두 모드 모두 네트워크 적재가 끝난 뒤 선택한 scope의 후속 Collector만 실행합니다.

### 4-1. 위 명령으로 실제 반영되는 데이터

기본 `--scope v1`로 실제 실행되는 Collector입니다.

| collector | 결과 | score |
|---|---|---|
| `BaseNetworkCollector` | walk_nodes / walk_edges | 없음 |
| `ParkPolygonCollector` | nature_layer + walk_edges.park_overlap_ratio | 없음 (`nature_score` 미갱신) |
| `SeoulBoundaryCollector` | seoul_administrative_boundary | 없음 |
| `SeoulWaterCollector` | seoul_water_polygons | 없음 |

### 4-2. `legacy-all`에서만 실행되는 데이터

`NatureCollector`, `SafetyCollector`, `ChildCollector`, `LandmarkCollector`, 사고 다발지역 갱신, 실외운동기구 갱신은 기본 V1 실행에서 제외됩니다. 필요하면 V1 승인 후 `collect_v1()`에 개별 추가합니다.

### 4-3. V1에서 보류한 데이터

다음 데이터는 `source_collector.py --scope legacy-all`로 raw 적재될 수 있지만, V1의 layer/score 생성에는 연결하지 않습니다.

| 파일 | query key | 상태 |
|---|---|---|
| 전국가로수길정보표준데이터.csv | `type=street_tree` | 보류 — `nature_score` 후보지만 collector 미구현 |
| 서울 둘레길.csv | `type=seoul_trail` | 보류 — CSV에는 좌표 컬럼이 없고, `RunningCourseCollector`는 `_TRAIL_COORDS` 하드코딩 좌표로 geometry 생성 중 |

전체 V1 사용 범위는 `analysis/data-governance/README.md`를 참고하세요.

## AI 응답 제한 방향

AI가 없는 정보를 만들지 않게 하려면 프롬프트만으로 막기보다 아래 흐름을 지키는 것이 좋습니다.

- DB/route engine/tool 결과를 먼저 계산합니다.
- LLM에는 계산 결과와 사용자 조건만 전달합니다.
- 프롬프트에는 제공된 데이터 밖의 장소, 수치, 시설 정보를 추측하지 말라고 명시합니다.
- 결과 객체에 없는 값은 "확인된 정보 없음"처럼 표현하도록 합니다.

즉, AI는 경로와 데이터를 결정하는 주체가 아니라, 이미 검증된 결과를 사용자에게 자연어로 설명하는 역할에 가깝게 두는 것이 안전합니다.

## 5. CSV Raw 데이터 재적재

`CSVSource`는 `CsvRawRepository.exists()` 검사로 이미 적재된 태그는 스킵합니다. 파일을 교체하거나 필터 로직을 수정한 뒤 재적재하려면 먼저 기존 데이터를 삭제해야 합니다.

### 특정 태그 재적재

```python
from src.repository.raw.csv_raw_repository import CsvRawRepository
from src.data.sources.csv_source import CSVSource

tag = "type=streetlight"
CsvRawRepository.delete(tag)
CSVSource().fetch_and_store("type", "streetlight")
```

### 전국 데이터 전체 서울 전용 재적재

전국 데이터 파일(`전국*`) 기반 태그는 `시도명` 또는 주소 컬럼으로 서울만 필터링됩니다. 필터 적용 전 데이터가 남아 있다면 아래처럼 재적재합니다.

```python
from src.repository.raw.csv_raw_repository import CsvRawRepository
from src.data.sources.csv_source import CSVSource

NATIONWIDE_TAGS = [
    ("type", "protection_zone"),
    ("type", "streetlight"),
    ("type", "bike_road"),
    ("type", "street_tree"),
]

source = CSVSource()
for key, value in NATIONWIDE_TAGS:
    deleted = CsvRawRepository.delete(f"{key}={value}")
    print(f"[삭제] {key}={value}: {deleted}건")
    source.fetch_and_store(key, value)
    print(f"[적재] {key}={value} 완료")
```

### 적재 현황 확인

```python
from src.database.postgresql import get_postgresql_db
from sqlalchemy import text

with get_postgresql_db() as db:
    rows = db.execute(text(
        "SELECT query_key, COUNT(*) FROM csv_raw GROUP BY query_key ORDER BY query_key"
    )).fetchall()
    for key, cnt in rows:
        print(f"{key}: {cnt}건")
```

### `seoul_trail` 주의사항

`서울 둘레길.csv`는 위경도 컬럼이 없어 시작/종료 위치를 카카오 키워드 검색으로 geocoding합니다. 적재 시 `KAKAO_API_KEY` 환경변수가 설정되어 있어야 하며, API 호출 수만큼 시간이 소요됩니다.

### `toilet` 주의사항

`공중화장실정보_서울특별시.csv`도 위경도 컬럼이 없어 도로명주소를 카카오 주소 검색으로 geocoding합니다. 서울 화장실 수천 건에 대해 API를 순차 호출하므로 시간이 오래 걸립니다.

## 6. 신규 CSV/XLSX 데이터 추가 방법

새 파일을 `src/data/raw`에 넣은 뒤 `src/data/sources/csv_source.py`를 아래 순서로 수정합니다.

**① 파일 컬럼 확인**

```python
import pandas as pd
df = pd.read_csv("src/data/raw/새파일.csv", encoding="cp949", nrows=3)
print(df.columns.tolist())
```

인코딩이 cp949가 아니면 `utf-8` 또는 `utf-8-sig`로 시도합니다.

**② `TAGS`에 추가**

```python
TAGS: list[tuple[str, str]] = [
    ...
    ("type", "new_tag"),  # 추가
]
```

**③ `_fetch_all` dispatch에 추가**

```python
dispatch = {
    ...
    "new_tag": self._load_new_tag,  # 추가
}
```

**④ `_load_xxx` 메서드 작성**

```python
def _load_new_tag(self):
    df = self._read_csv("새파일.csv")
    cols = ["위도", "경도", "시설명", "소재지도로명주소", "시도명"]
    df = df[[c for c in cols if c in df.columns]]
    #         lat,   lon,    name,      addr,           city_col(서울 필터)
    return df, "위도", "경도", "시설명", "소재지도로명주소", "시도명", None, None
```

반환 순서: `df, lat_col, lon_col, name_col, addr_col, city_col, end_lat_col, end_lon_col`
- LINESTRING(기점→종점)이면 `end_lat_col`, `end_lon_col` 지정
- 이미 서울 전용 파일이면 `city_col=None`

**⑤ 적재 실행**

```bash
poetry run python -c "
from src.data.sources.csv_source import CSVSource
CSVSource().fetch_and_store('type', 'new_tag')
"
```

> 새 데이터를 layer/score/profile에 반영하려면 V1 사용 목적을 먼저 정하고 source, collector, repository 연결을 함께 구현해야 합니다.
