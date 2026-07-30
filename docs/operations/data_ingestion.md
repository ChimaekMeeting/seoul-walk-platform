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
| `전국도시공원정보표준데이터.csv` | 공공데이터포털 | 검증·메타데이터 보조 원본 |
| `전국가로수길정보표준데이터.csv` | 공공데이터포털 | `street_tree` |
| `서울 둘레길.csv` | 서울 열린데이터광장 | `seoul_trail` |
| `서울시 공중화장실 위치정보.csv` | 서울 열린데이터광장 | `toilet` |
| `공중화장실정보_서울특별시.csv` | 서울 열린데이터광장 | 화장실 운영 속성 보조 원본 |
| `서울시 버스정류소 위치정보.csv` | 서울 열린데이터광장 | `bus_stop` |
| `소상공인시장진흥공단_상가(상권)정보_서울_202603.csv` | 소상공인시장진흥공단 | `commercial` |
| `서울시 자치구별 도보 네트워크 공간정보.csv` | 서울 열린데이터광장 | (walk_network) |
| `행정구역 법정동 경계.shp` 및 sidecar | 서울 열린데이터광장 | 자치구 공간 분류 기준 |
| `서울시 하천.geojson` | 서울 열린데이터광장 | (river) |

> **주의:** 전국 데이터(`전국*` 파일)는 적재 시 서울 데이터만 필터링됩니다. 필터 기준은 `CSVSource.clean()` 내 `city_col` 설정을 따릅니다.

RAW 적재 단계에서는 같은 좌표에 서로 다른 시설·센서가 있을 수 있으므로 좌표만으로 행을 삭제하지 않습니다. 서비스 Layer에서 위치 단위 점수가 필요한 데이터만 해당 collector가 좌표를 묶습니다.

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

`toilet` 적재는 좌표가 포함된 `서울시 공중화장실 위치정보.csv`를 공간 주 원본으로 사용합니다. 원본의 연번 `266601`(을지로3가파출소)과 `266704`(충무로119안전센터)는 서울 중구 시설인데 주소와 좌표가 대전 중구로 잘못 제공되어, `CSVSource._load_toilet()`가 원본을 수정하지 않고 검증된 서울 주소·좌표로 덮어씁니다.

`공중화장실정보_서울특별시.csv`는 운영시간·편의시설 등 속성 보조 원본으로만 사용하며, 위치 원본과 결합되지 않은 항목에만 추후 geocoding을 검토합니다.

### `streetlight` 주의사항

스마트가로등은 `시도명=서울특별시`인 317개 RAW 설비를 보존합니다. 단순 서울 bbox에는 경기도 안양시 등 39개 행이 함께 들어오므로 좌표 범위만으로 서울을 선택하지 않습니다.

서로 다른 주소가 동일 좌표로 제공된 행 가운데 `서울특별시 구로구 개봉로 8`과 `서울특별시 구로구 구로동로 34`는 주소 검색 결과 원본 좌표 오류가 확인되어 `CSVSource._load_streetlight()`에서 정정합니다. 정정 후 317개 설비는 307개 위치이며, `SafetyCollector`가 같은 위치의 설비를 하나의 `safety_layer` Point로 집계해 안전 점수를 한 번만 반영합니다.

### `cctv` 주의사항

`서울시CCTV정보.xlsx`의 57,760개 RAW와 `카메라대수`는 모두 보존합니다. 서울 주소인데 좌표가 서울 밖이거나 경도 `216.9947`처럼 유효 범위를 벗어난 14건은 `CSVSource._load_cctv()`가 `번호`를 기준으로 검증된 주소 검색 좌표를 적용합니다.

정정 후 57,760개 RAW는 44,710개 위치입니다. `SafetyCollector`는 같은 위치를 하나의 `safety_layer` Point로 묶어 중복 가점을 막습니다. 구별 설치·제공량의 차이가 크므로 미설치 지역을 위험으로 감점하지 않고, 위치가 확인된 구간에만 제한적으로 가점합니다.

### `protection_zone` 주의사항

어린이보호구역은 `소재지도로명주소`가 `서울특별시`로 시작하는 1,614개 시설만 적재합니다. `서울` 포함 검색은 경기도 시흥시 `서울대학로`를 잘못 포함하고, 서울 bbox 검색은 하남·의정부 등 주변 지역을 포함하므로 사용하지 않습니다.

같은 좌표의 초등학교와 병설유치원 등 서로 다른 시설 RAW는 모두 보존합니다. `ChildCollector`는 경로 반영 시 이를 1,466개 위치로 묶어 동일 장소를 중복 계산하지 않습니다. 이 데이터는 안전 보장 가점이 아니라 어린이보호구역과 차량 주의 의미로 해석합니다.

### `street_tree` 주의사항

가로수길 원본에서 `제공기관명`이 `서울특별시`로 시작하는 행은 819건입니다. 서울 범위를 벗어난 좌표 오류는 65건이고 시작·종료 좌표가 같은 행은 9건이며, 두 조건에 동시에 해당하는 행이 2건입니다. 따라서 중복을 제외한 72건은 원본 파일에 보존하되 공간 입력에서 제외합니다.

`CSVSource._load_street_tree()`는 양 끝 좌표가 서울 범위에 있고 길이가 0이 아닌 747개 Line만 적재합니다. 사용 가능한 Line은 15개 구에만 분포합니다. 시작·종료점 직선은 실제 도로 형상을 단순화한 것이므로 WalkEdge에 연결하기 전에 도로명과 공간 근접성을 함께 검증해야 합니다.

### `전국도시공원정보표준데이터` 주의사항

현재 원본 18,499행 중 `제공기관명`이 `서울특별시`로 시작하는 1,786행을 서울 자료로 확정합니다. 좌표 bbox만 사용하면 구리시 등 인접 지역이 포함되므로 서울 추출 기준으로 사용하지 않습니다.

서울 자료는 좌표 결측 없이 25개 구를 포함하지만, 서로 다른 공원이 같은 대표 좌표를 공유하는 사례가 있어 1,764개 좌표 위치로 병합하지 않습니다. 1,786행의 관리번호·명칭·구분·면적·시설 정보는 원본으로 보존하고 공원 Polygon의 누락·속성 검증에만 사용합니다. Point를 WalkEdge나 자연 Score에 직접 연결하지 않으며, 공원 공간 판정은 `ParkPolygonCollector`가 읽는 1,888개 Polygon/MultiPolygon을 기준으로 합니다.

### 자치구 공간 분류 기준

`행정구역 법정동 경계.shp`와 같은 이름의 `.shx`, `.dbf`, `.prj`를 한 폴더에 보존합니다. 현재 원본은 EPSG:5186의 유효한 법정동 geometry 467개이며, `COL_ADM_SE` 5자리 자치구 코드로 dissolve하면 서울 25개 자치구 Polygon/MultiPolygon과 605.73km²의 결합 면적을 얻습니다.

자치구 필드나 서울 주소가 있는 원본은 해당 값을 우선합니다. 자치구 필드가 없는 Point·Line·Polygon만 이 경계와 공간 결합합니다.

- 경계 내부 Point는 포함된 자치구를 사용합니다.
- 경계 밖의 접경 Point는 최근접 자치구와 거리(m)를 함께 기록합니다.
- 둘 이상의 자치구 경계와 겹치는 Point는 원본의 주소·관리기관 자치구를 우선하고, 해당 속성이 없을 때만 결정적인 tie-break 기준을 적용합니다.
- Polygon은 대표점 개수뿐 아니라 서울 경계와 실제 교차한 면적을 사용합니다.
- 서울 경계 밖 geometry는 원본에는 보존하되 서울 WalkEdge의 교차·Score 계산에서는 제외합니다.

현재 버스정류소 11,253개 중 11,237개는 자치구 경계 내부이고, 접경 16개는 최근접 자치구까지 0.24~71.89m입니다. 모두 25개 구에 배정할 수 있습니다.

공원 Polygon 1,888개 중 중심점이 서울 밖인 4개는 `서울대공원·청계산` 관련 geometry로 과천에 있습니다. 이 4개도 원본에는 보존하지만 서울 경계 밖 부분은 서비스 공간 판정에서 제외합니다.

`서울시 둘레길 선형 위치정보`와 `서울시 문화길 선형 위치정보` CSV는 파일명과 달리 현재 원본에서 유효한 Line geometry를 제공하지 않습니다. 둘레길 `SHAPE`는 `[B@...` 문자열이고 문화길은 좌표점과 파일경로만 있으므로, 좌표점을 순서대로 연결해 임의의 선을 만들지 않습니다. 유효한 SHP·GeoJSON·WKT·GPX·KML/KMZ 원본을 확보할 때까지 위치 참고 자료로만 보존합니다.

### WalkNode·WalkEdge 연결 기준

원본 Point를 WalkNode로 새로 만들지 않습니다. WalkNode와 WalkEdge는 도보 네트워크 원본으로만 생성하며, 외부 데이터는 다음 방식으로 기존 그래프에 연결합니다.

| 입력 형태 | 연결 방식 | 최대 거리·검증 |
|---|---|---|
| CCTV·스마트가로등·어린이보호구역·상권 | H3 resolution 9 셀별 밀도를 Edge 중심점의 같은 H3 셀에 Score로 전달 | 셀별 중복 집계와 최대 가점 제한. H3는 정확한 Edge 연결로 해석하지 않음 |
| 화장실·버스정류소·리프트·엘리베이터 | 최근접 WalkNode·WalkEdge에 POI 관계 저장 | 최대 50m. 초과 Point는 지도 표시 전용 |
| 가로수길 | Line 50m 안의 후보 WalkEdge 탐색 | 도로명과 연속성이 확인된 Edge만 Tag·제한 가점 |
| 보행자우선도로 | Line 20m 안의 후보 WalkEdge 탐색 | 도로명과 연속성이 확인된 Edge만 `pedestrian_priority` Tag |
| 공원 | Polygon과 WalkEdge의 실제 교차 길이 비율 | `park_overlap_ratio`; 중심점 근접 사용 금지 |
| 보행 겸용 자전거도로 | 기·종점과 도로명으로 실제 네트워크 경로 복원 | 기·종점 직선 주변 Edge 자동 태그 금지 |
| 외부 터널 | 기존 `raw_is_tunnel` Edge와 비교 | 자동 차단 금지. 보도폭 검증과 쾌적도 감점 후보로만 사용 |
| 둘레길·문화길 | 유효한 Line geometry 확보 후 별도 검증 | 현재 원본으로 연결 금지 |

현재 `SafetyCollector`와 `ChildCollector`의 Score는 최근접 Edge를 찾지 않습니다. Layer Point와 WalkEdge 중심점을 각각 H3 resolution 9 셀로 변환하고, 같은 셀의 Point 수를 로그 정규화해 Edge Score로 저장합니다. 정확한 도로 의미가 필요한 `school_zone`, `vehicle_caution`, `pedestrian_priority`, `tunnel` 등의 Tag는 이 Score 처리와 별도로 WalkEdge에 저장해야 합니다.

경로 생성 시에는 프로필과 `Weights`가 Score의 중요도를 조절하고, `blocked_tags`는 공간 검증이 완료된 WalkEdge Tag에만 적용합니다. 원본 Point나 H3 셀을 직접 차단 대상으로 사용하지 않습니다.

### 결측·편향 처리 기준

적재 과정은 원본 결측과 실제 시설 부재를 구분합니다.

- 원본 행과 원본 값은 보존하고 정제값·보정 근거·제외 사유를 별도로 관리합니다.
- 주소·시설 식별값·공식 위치처럼 재현 가능한 근거가 있는 오류만 보정합니다.
- 결측 숫자를 `0`, 결측 좌표를 `(0, 0)`으로 채우지 않습니다. 의미가 확인되지 않은 숫자 `0`도 실제 시설·보도 없음으로 단정하지 않습니다.
- Point 좌표가 없으면 공간 입력에서 제외하고, Line의 시작·종료 좌표가 불완전하면 임의의 선을 만들지 않습니다.
- 동일 위치의 반복 행은 위치·H3 셀별로 집계하되 좌표만 같은 서로 다른 시설은 자동 병합하지 않습니다.
- 일부 자치구에만 제공된 데이터는 확인된 위치에만 제한 가점하고 미제공 자치구를 감점하지 않습니다.
- 대량 Point는 개별 건수를 그대로 더하지 않고 H3 셀 또는 거리 단위로 정규화해 최대 가점을 적용합니다.
- 서울 경계 밖 geometry는 원본에 보존하고 서울 WalkEdge Score 계산에서는 제외합니다.
- 도보망 연결 한도를 넘는 Point는 다른 Edge에 강제로 연결하지 않고 표시 전용으로 남깁니다.

25개 원본별 확정 상태와 예외는 [`dataset_roles.md`](../data/dataset_roles.md)의 `11.5 결측·편향 처리 계약 확정`을 단일 기준으로 사용합니다.

### 최종 연동·재적재 순서

DB 재적재는 최종 역할을 문서에 적은 직후가 아니라, 해당 역할을 만드는 Entity·Repository·Collector 구현이 끝난 뒤 실행합니다.

1. `dataset_roles.md` 11.6의 최종 필드·Score·Tag·POI 계약을 기준으로 구현 범위를 고정합니다.
2. 필요한 Entity·Repository·Collector와 공간 변환기를 구현하고 단위 테스트를 통과시킵니다.
3. 개발 중에는 `upsert`로 작은 범위를 확인하고, 최종 스냅샷 검증에서 `rebuild`를 실행합니다.
4. NODE·LINK·Layer·Score·POI 건수, 결측, 참조 무결성, 공간 범위를 확인합니다.
5. `GraphRepository`가 새 필드와 Tag를 NetworkX에 전달하도록 수정합니다.
6. 프로필·`Weights`·Scoring·`blocked_tags`를 확정 입력 계약에 맞추고 경로 회귀 테스트를 실행합니다.
7. 서버를 재시작해 메모리 Graph를 다시 로드한 뒤 모바일 앱의 실제 경로를 확인합니다.
8. 코드·실행 결과와 일치하지 않는 과거 데이터 문서는 링크를 확인한 뒤 통합하거나 삭제합니다.

`rebuild`는 기존 WalkEdge Score와 Layer 연결 결과를 초기화하므로 대상 DB 백업과 활성 Collector 재실행 순서를 확인하기 전에는 운영 DB에서 실행하지 않습니다.

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
