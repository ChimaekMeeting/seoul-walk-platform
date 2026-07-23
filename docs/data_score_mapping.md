# 데이터-score 연결표

`src/data/raw`에 있는 원본 파일이 실제로 어떤 score/layer/collector와 연결되어 있는지,
그리고 QA가 로컬에서 같은 결과를 재현하려면 어떤 명령을 실행해야 하는지를 정리한 문서입니다.

이 문서는 조사 결과만 담고 있습니다. **코드/DB schema는 변경하지 않았고, `data_collector.py`의
주석 처리된 collector도 그대로 둔 상태**를 기준으로 작성했습니다.

## 1. raw 데이터 연결 상태 표

| dataset/file | source_type | source_collector | data_collector | raw_table | layer | score | V1 판단 | status | note |
|---|---|---|---|---|---|---|---|---|---|
| 서울시 자치구별 도보 네트워크 공간정보.csv | csv | △ `CSVSource.load_walk_network()`가 직접 읽음(TAGS 미경유) | `BaseNetworkCollector` | none | walk_nodes / walk_edges | 없음 | 사용 | **활성** | 경로 탐색 기반 네트워크, score 컬럼 없음 |
| 전국어린이보호구역표준데이터.csv | csv | ✅ `CSVSource.TAGS["protection_zone"]` | `ChildCollector` | csv_raw | child_layer | child_score | 사용 | **활성** | |
| 전국스마트가로등표준데이터.csv | csv | ✅ `CSVSource.TAGS["streetlight"]` | `SafetyCollector` | csv_raw | safety_layer | safety_score | 사용 | **활성** | |
| 서울시CCTV정보.xlsx | xlsx | ✅ `CSVSource.TAGS["cctv"]` | `SafetyCollector` | csv_raw | safety_layer | safety_score | 사용 | **활성** | |
| 서울시 주요 공원현황.csv | csv | ✅ `CSVSource.TAGS["running_park"]` | `RunningCourseCollector` | csv_raw | running_layer | running_score | 보류 | ⚠️ **비활성** | `RunningCourseCollector().save()`가 주석 처리되어 기본 명령으로는 실행되지 않음 |
| 전국자전거도로표준데이터.csv | csv | ✅ `CSVSource.TAGS["bike_road"]` | `RunningCourseCollector` | csv_raw | running_layer | running_score | 보류 | ⚠️ **비활성** | 위와 동일 사유 |
| 서울시 하천.geojson | geojson | ❌ source_collector 미경유(`RunningCourseCollector`가 파일을 직접 `gpd.read_file()`) | `RunningCourseCollector` | none | running_layer | running_score | 보류 | ⚠️ **비활성** | raw 테이블 적재 단계 자체가 없고, collector도 비활성 |
| 전국가로수길정보표준데이터.csv | csv | ✅ `CSVSource.TAGS["street_tree"]` | ❌ 없음 | csv_raw | 미정 | 미정 | 보류 | **raw-only** | raw에는 적재되지만 V1 layer/score에는 연결하지 않음 |
| 서울 둘레길.csv | csv | ✅ `CSVSource.TAGS["seoul_trail"]` | 직접 연결 없음 | csv_raw | 미정 | 미정 | 보류 | **raw-only** | `RunningCourseCollector`는 이 파일 대신 `_TRAIL_COORDS` 하드코딩 좌표를 사용 |

표에 없는 `nature_layer`(OSM 녹지), `landmark_layer`(TourAPI), `play_facility`(공공데이터 API)는
`src/data/raw`의 로컬 파일이 아니라 OSM/공공 API 기반이라 이 표의 범위 밖입니다(아래 "score별 데이터 근거"에서만 함께 정리).

## 2. score별 데이터 근거

| score | 데이터 근거 | raw 파일 여부 | 비고 |
|---|---|---|---|
| `safety_score` | 전국스마트가로등표준데이터.csv, 서울시CCTV정보.xlsx | ✅ raw 파일 | `SafetyCollector` 활성, 기본 명령으로 반영됨 |
| `child_score` | 전국어린이보호구역표준데이터.csv + 어린이놀이시설(공공데이터 API) | ✅ raw 파일 + API | `ChildCollector` 활성, raw 파일분은 기본 명령으로 반영됨 |
| `nature_score` | OSM natural/landuse/leisure 태그(녹지) | ❌ raw 파일 아님(OSM API) | `NatureCollector` 활성. 전국가로수길정보는 V1에서 보류 |
| `running_score` | 서울시 주요 공원현황.csv, 전국자전거도로표준데이터.csv, 서울시 하천.geojson, 하드코딩된 둘레길/등산로 좌표 | ✅ raw 파일(일부) | `RunningCourseCollector` **자체가 비활성**이라 raw 파일이 있어도 현재는 반영되지 않음 |
| `landmark_score` | TourAPI 관광지/문화시설 | ❌ raw 파일 아님(공공 API) | `LandmarkCollector` 활성, raw 파일과 무관 |
| `slope_score` | (별도 경사 계산, `SlopeCalculator`) | - | `data_collector.py` 39-40행에서 주석 처리되어 **비활성**. 이 문서가 다루는 raw 파일과 직접 연결된 근거 없음 |

## 3. QA 재현 명령어

아래 3단계만으로 "현재 활성 상태인" 데이터를 그대로 재현할 수 있습니다.
각 명령은 한 번에 붙여 넣지 말고, 이전 단계가 성공한 뒤 다음 단계를 실행합니다.

사전 조건:

- PostgreSQL/Valkey 컨테이너가 실행 중이어야 합니다: `docker-compose up -d`
- `PUBLIC_DATA_API_KEY`는 어린이놀이시설 API와 TourAPI 활용신청이 모두 승인된 data.go.kr 서비스키여야 합니다.
- `KAKAO_API_KEY`가 설정되어 있어야 합니다.

```bash
# 1) 테이블 생성
poetry run python -c "from src.entity.base import init_db; init_db()"

# 2) raw 데이터 적재 (OSM/Kakao/공공데이터/CSV·XLSX)
poetry run python -m src.data.source_collector

# 3) 서비스용 도메인 데이터 적재 (layer + walk_edges.*_score)
poetry run python -m src.data.data_collector
```

주의: `poetry run python -m src.main`은 FastAPI 서버를 실행하고 종료되지 않으므로,
QA 재현용 테이블 생성 명령으로는 위의 `init_db()` 원샷 명령을 사용합니다.

- 각 collector는 해당 layer가 이미 채워져 있으면 자동으로 스킵합니다. 깨끗하게 재현하려면 DB를 초기화한 뒤 위 3단계를 다시 실행하세요.
- 위 명령으로 실제 반영되는 score: `safety_score`, `child_score`, `nature_score`(OSM만), `landmark_score`. walk_nodes/walk_edges 기본 네트워크도 함께 채워집니다.
- 위 명령으로 **반영되지 않는** score: `running_score`(collector 비활성), `slope_score`(collector 비활성).
- street_tree/seoul_trail은 raw에는 적재될 수 있지만 V1 layer/score에는 연결되지 않습니다.

### 3-1. 로컬 실행 확인 결과

feat/209 브랜치에서 위 흐름을 재현하며 확인한 결과입니다.

| 항목 | 결과 |
|---|---|
| `source_collector` | OSM/Kakao/Public/CSV·XLSX raw 적재 완료 |
| `walk_nodes` / `walk_edges` | 적재 완료. 재실행 시 "이미 적재됨, 스킵" |
| `nature_score` | `279,016`건 업데이트 확인 |
| `safety_score` | `279,016`건 업데이트 확인 |
| `child_score` | `279,016`건 업데이트 확인 |
| `landmark_score` | `279,016`건 업데이트 확인 |
| 서울 행정구역 경계 | `1`개 폴리곤 적재 확인 |
| 서울 수계 폴리곤 | `411`개 폴리곤 적재 확인 |

실행 중 확인한 주의사항:

- DB 컨테이너가 내려간 상태에서 실행하면 `127.0.0.1:5434 connection refused`가 발생합니다. 이 경우 `docker-compose up -d`로 컨테이너만 다시 시작하고, `docker-compose down -v`는 사용하지 않습니다.
- 어린이놀이시설 API 활용신청/권한이 없으면 `PublicSource`의 `play_facility` 단계에서 `403 Forbidden`이 발생하고, 이후 Public/CSV 적재가 중단될 수 있습니다.
- `waterway=riverbank`는 OSM 응답이 없을 수 있으나, `natural=water` 등 다른 태그로 수계 폴리곤 적재가 완료되면 전체 적재 실패로 보지 않습니다.

## 4. V1 보류 데이터 사용 원칙

- raw 적재 여부와 layer/score 사용 여부를 분리해서 판단합니다.
- `street_tree`, `seoul_trail`처럼 raw-only인 데이터는 경로 점수나 AI 응답의 확정 근거로 사용하지 않습니다.
- V1에 새 데이터를 연결할 때는 `analysis/data-governance/README.md`의 상태 표를 먼저 갱신합니다.

## 5. 비활성 collector 목록 / 팀 확인 필요 항목

| collector | 상태 | 위치 | 팀 확인 필요 사항 |
|---|---|---|---|
| `RunningCourseCollector` | `data_collector.py`에서 주석 처리 | `src/data/collectors/running_collector.py` | V1 기본 적재에서 보류. 활성화 시 `running_score` 결과와 경로 회귀 검증 필요 |
| `SlopeCalculator` | `data_collector.py`에서 주석 처리 | `src/data/collectors/slope_collector.py` | `slope_score` 반영 방식과 running 모드 해석을 함께 검증한 뒤 활성화 |
| 서울 둘레길.csv ↔ `RunningCourseCollector._TRAIL_COORDS` | CSV는 메타데이터, 코드는 좌표 하드코딩 | `src/data/collectors/running_collector.py` | CSV에는 좌표 컬럼이 없어 `_TRAIL_COORDS`를 바로 대체할 수 없음. 단기적으로는 하드코딩 좌표를 유지하고 CSV를 거리/난이도/설명 보강용으로 연결하는 방향이 적절함 |
| street_tree (`전국가로수길정보표준데이터.csv`) | raw-only, collector 미구현 | `CSVSource` | V1 보류. 별도 검증 전 `nature_score` 근거로 사용하지 않음 |

### 5-1. 서울 둘레길 CSV와 `_TRAIL_COORDS` 비교

`서울 둘레길.csv`는 21개 둘레길 코스의 공식 메타데이터를 담고 있고,
`RunningCourseCollector._TRAIL_COORDS`도 21개 trail 후보 좌표를 가지고 있습니다.
두 목록은 대부분 순서와 코스가 일치하지만, CSV에는 위도/경도 컬럼이 없습니다.

CSV에 있는 컬럼:

- `둘레길 번호`
- `둘레길 명`
- `난이도[한글]`
- `둘레길 설명`
- `세부코스명`
- `시작 위치`
- `종료 위치`
- `스탬프함 위치`
- `둘레길 길이 (km)`
- `소요시간`
- `스마트 서울맵 URL`
- `파일다운로드 페이지 링크`

일부 코스명은 CSV가 더 넓은 명칭을 사용하고, 코드의 `_TRAIL_COORDS`는 대표 지점명을 사용합니다.

| CSV `둘레길 명` | `_TRAIL_COORDS` key |
|---|---|
| 망우·용마산 | 용마산 |
| 장지·탄천 | 탄천 |
| 대모·구룡산 | 구룡산 |
| 노을·하늘공원 | 하늘공원 |
| 봉산·앵봉산 | 앵봉산 |

좌표 보완 방향:

- `src/data/utils/geocode_utils.py`에는 Kakao 주소 geocoding 유틸이 있습니다.
- 다만 `서울 둘레길.csv`의 `시작 위치`/`종료 위치`/`스탬프함 위치`는 주소라기보다 장소명에 가까워, 주소 검색(`/v2/local/search/address.json`)보다 키워드 검색(`/v2/local/search/keyword.json`)이 더 적합할 수 있습니다.
- Kakao geocoding/keyword 결과는 자동 확정하지 않고, 후보 좌표를 별도로 검토한 뒤 반영합니다.
