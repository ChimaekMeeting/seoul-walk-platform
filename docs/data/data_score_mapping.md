# 데이터와 Score 연결표

`src/data/raw`에 있는 원본 파일이 실제로 어떤 score/layer/collector와 연결되어 있는지,
그리고 QA가 로컬에서 같은 결과를 재현하려면 어떤 명령을 실행해야 하는지를 정리한 문서입니다.

feat/209 재현 결과는 과거 전체 파이프라인 기록으로 보존합니다. 현재 V1 실행 범위와 명령은
`docs/operations/data_ingestion.md`를 기준으로 하며, `legacy-all`을 명시하지 않으면 보류 Score를 계산하지 않습니다.

공원 Polygon 매핑 방식의 비교 결과와 결정 근거는
`analysis/raw/park_walkedge_mapping_validation.ipynb`에 보존합니다.

## 1. raw 데이터 연결 상태 표

| dataset/file | source_type | source_collector | data_collector | raw_table | layer | score | V1 판단 | status | note |
|---|---|---|---|---|---|---|---|---|---|
| 서울시 자치구별 도보 네트워크 공간정보.csv | csv | △ `CSVSource.load_walk_network()`가 직접 읽음(TAGS 미경유) | `BaseNetworkCollector` | none | walk_nodes / walk_edges | 없음 | 사용 | **활성** | 경로 탐색 기반 네트워크, score 컬럼 없음 |
| 서울시 생활권계획 시설(공원) 공간정보 Shapefile | shp | 직접 읽음 | `ParkPolygonCollector` | none | nature_layer | `park_overlap_ratio` | 사용 | **V1 적재 활성·알고리즘 미연결** | Edge 길이 중 Polygon 내부 비율을 저장. `nature_score`는 갱신하지 않으며 `GraphRepository`도 아직 이 필드를 전달하지 않음. 서울 경계 밖 Polygon 부분 제외는 보완 필요 |
| 전국어린이보호구역표준데이터.csv | csv | ✅ `CSVSource.TAGS["protection_zone"]` | `ChildCollector` | csv_raw | child_layer | child_score | 제한 사용 | `legacy-all` 전용 | 위치 H3 셀과 Edge 중심점 H3 셀이 같을 때 Score 반영. `school_zone`·`vehicle_caution` Edge Tag는 미구현 |
| 전국스마트가로등표준데이터.csv | csv | ✅ `CSVSource.TAGS["streetlight"]` | `SafetyCollector` | csv_raw | safety_layer | safety_score | 제한 사용 | `legacy-all` 전용 | 위치 H3 셀과 Edge 중심점 H3 셀이 같을 때 제한 Score 반영 |
| 서울시CCTV정보.xlsx | xlsx | ✅ `CSVSource.TAGS["cctv"]` | `SafetyCollector` | csv_raw | safety_layer | safety_score | 제한 사용 | `legacy-all` 전용 | 위치 H3 셀과 Edge 중심점 H3 셀이 같을 때 제한 Score 반영 |
| 서울시 주요 공원현황.csv | csv | ✅ `CSVSource.TAGS["running_park"]` | `RunningCourseCollector` | csv_raw | running_layer | running_score | 메타데이터만 사용 | ⚠️ **비활성** | 대표점의 도보망 연결률이 낮아 Edge Score로 사용하지 않음. 공원 공간 판정은 Polygon 기준 |
| 전국자전거도로표준데이터.csv | csv | ✅ `CSVSource.TAGS["bike_road"]` | `RunningCourseCollector` | csv_raw | running_layer | running_score | 경로 복원 전 보류 | ⚠️ **비활성** | 현재 collector는 기점 Point만 사용. 기·종점 직선의 전체 50m 연결률이 낮아 Edge 태그 자동 변환 금지 |
| 서울시 하천.geojson | geojson | ❌ source_collector 미경유(`RunningCourseCollector`가 파일을 직접 `gpd.read_file()`) | `RunningCourseCollector` | none | running_layer | running_score | 보류 | ⚠️ **비활성** | raw 테이블 적재 단계 자체가 없고, collector도 비활성 |
| 전국가로수길정보표준데이터.csv | csv | ✅ `CSVSource.TAGS["street_tree"]` | ❌ 없음 | csv_raw | 미정 | 미정 | 제한 사용 계약 | **raw-only** | 50m 후보 Edge에서 도로명·연속성 검증 후 `street_tree`·`shade_candidate` 연결 필요 |
| 전국보행자우선도로표준데이터.csv | csv | ❌ 없음 | ❌ 없음 | none | 미정 | 미정 | 연결 계약 확정 | **미구현** | 20m 후보 Edge에서 도로명·연속성 검증 후 `pedestrian_priority` 연결 필요 |
| 국토교통부_전국도로터널정보표준데이터_20251231.csv | csv | ❌ 없음 | ❌ 없음 | none | 기존 WalkEdge 검증 | 쾌적도 감점 후보 | 제한 사용 | **미구현** | 기존 `raw_is_tunnel` 우선. 외부 원본으로 자동 차단 금지 |
| 서울시 지하철역 연계 지하도 공간정보.csv | csv | ❌ 없음 | ❌ 없음 | none | 기존 WalkEdge 검증 | 미정 | 보류 | **미구현** | 50m 연결은 가능하지만 V1 반영 보류 |
| 서울시 공중화장실 위치정보.csv | csv | ✅ `CSVSource.TAGS["toilet"]` | ❌ 없음 | csv_raw | 미정 | 미정 | 위치 사용 승인 | **raw-only** | 50m 안의 최근접 WalkNode·WalkEdge POI 연결 필요. 밖의 Point는 표시 전용 |
| 서울시 버스정류소 위치정보.csv | csv | ✅ `CSVSource.TAGS["bus_stop"]` | ❌ 없음 | csv_raw | 미정 | 미정 | 연결 계약 확정 | **raw-only** | 50m 안의 최근접 WalkNode·WalkEdge 교통 POI 연결 필요 |
| 서울시 지하철 출입구 리프트 위치정보.csv | csv | ❌ 없음 | ❌ 없음 | none | 미정 | 미정 | 연결 계약 확정 | **미구현** | 최근접 출입구 WalkNode·WalkEdge 접근성 POI 연결 필요 |
| 서울시 지하철역 엘리베이터 위치정보.csv | csv | ❌ 없음 | ❌ 없음 | none | 미정 | 미정 | 연결 계약 확정 | **미구현** | 최근접 출입구 WalkNode·WalkEdge 접근성 POI 연결 필요 |
| 소상공인시장진흥공단_상가(상권)정보_서울_202603.csv | csv | ✅ `CSVSource.TAGS["commercial"]` | ❌ 없음 | csv_raw | 미정 | 미정 | 연결 계약 확정 | **raw-only** | 개별 Point 합산 금지. H3 셀별 업종·밀도와 가점 상한 구현 필요 |
| 서울시 둘레길 선형 위치정보·문화길 선형 위치정보 | csv | ❌ 없음 | ❌ 없음 | none | none | none | 보류 | **미구현** | 유효한 Line geometry 확보 전 Score·Tag·`blocked_tags` 연결 금지 |
| 서울 둘레길.csv | csv | ✅ `CSVSource.TAGS["seoul_trail"]` | 직접 연결 없음 | csv_raw | 미정 | 미정 | 보류 | **raw-only** | 코스 메타데이터만 보존. `RunningCourseCollector`의 `_TRAIL_COORDS`는 이 원본의 실제 선형이 아님 |

표에 없는 `nature_layer`(OSM 녹지), `landmark_layer`(TourAPI), `play_facility`(공공데이터 API)는
`src/data/raw`의 로컬 파일이 아니라 OSM/공공 API 기반이라 이 표의 범위 밖입니다(아래 "score별 데이터 근거"에서만 함께 정리).

## 2. score별 데이터 근거

| score | 데이터 근거 | raw 파일 여부 | 비고 |
|---|---|---|---|
| `safety_score` | 전국스마트가로등표준데이터.csv, 서울시CCTV정보.xlsx | ✅ raw 파일 | V1 기본 실행에서 보류, `legacy-all` 전용 |
| `child_score` | 전국어린이보호구역표준데이터.csv + 어린이놀이시설(공공데이터 API) | ✅ raw 파일 + API | V1 기본 실행에서 보류, `legacy-all` 전용 |
| `nature_score` | 도보망 원본 `raw_is_park_green` + 서울시 공원 Polygon `park_overlap_ratio` | ✅ CSV + Shapefile | 두 근거는 별도 보존하며 V1 결합 정책은 아직 미정. `ParkPolygonCollector`는 `nature_score`를 갱신하지 않음. 기존 OSM `NatureCollector`는 `legacy-all` 전용 |
| `running_score` | 서울시 주요 공원현황.csv, 전국자전거도로표준데이터.csv, 서울시 하천.geojson, 하드코딩된 둘레길/등산로 좌표 | ✅ raw 파일(일부) | `RunningCourseCollector` **자체가 비활성**이라 raw 파일이 있어도 현재는 반영되지 않음 |
| `landmark_score` | TourAPI 관광지/문화시설 | ❌ raw 파일 아님(공공 API) | `LandmarkCollector` 활성, raw 파일과 무관 |
| `slope_score` | (별도 경사 계산, `SlopeCalculator`) | - | `data_collector.py` 39-40행에서 주석 처리되어 **비활성**. 이 문서가 다루는 raw 파일과 직접 연결된 근거 없음 |

## 3. QA 재현 명령어

아래 명령은 현재 V1 범위만 재현합니다.
각 명령은 한 번에 붙여 넣지 말고, 이전 단계가 성공한 뒤 다음 단계를 실행합니다.

사전 조건:

- PostgreSQL/Valkey 컨테이너가 실행 중이어야 합니다: `docker-compose up -d`
```bash
# 1) 테이블 생성
poetry run python -c "from src.entity.base import init_db; init_db()"

# 2) V1 서비스 데이터 적재
poetry run python -m src.data.data_collector --scope v1 --network-mode rebuild
```

주의: `poetry run python -m src.main`은 FastAPI 서버를 실행하고 종료되지 않으므로,
QA 재현용 테이블 생성 명령으로는 위의 `init_db()` 원샷 명령을 사용합니다.

- 위 명령은 공원 Polygon 기반 `park_overlap_ratio`까지 계산합니다. `nature_score`는 별도 점수 정책이 확정되기 전까지 계산하지 않습니다.
- `safety_score`, `child_score`, `landmark_score`, `running_score`, `slope_score`는 V1 기본 실행에서 계산하지 않습니다.
- OSM/Kakao/Public/보조 CSV 전체 재현은 `--scope legacy-all`을 명시해야 합니다.

### 3-1. 로컬 실행 확인 결과

feat/209 브랜치에서 과거 전체 파이프라인을 재현하며 확인한 결과입니다. 현재 V1 결과가 아닙니다.

| 항목 | 결과 |
|---|---|
| `source_collector` | OSM/Kakao/Public/CSV·XLSX raw 적재 완료 |
| `walk_nodes` / `walk_edges` | 적재 완료. 재실행 시 "이미 적재됨, 스킵" |
| `nature_score` | 과거 전체 파이프라인에서 `279,016`건 업데이트 확인. 현재 V1에서는 갱신하지 않음 |
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
- `street_tree`, `seoul_trail`처럼 raw-only인 데이터는 연결 계약이 확정됐더라도 실제 Edge 변환기가 구현되기 전에는 경로 점수나 AI 응답의 확정 근거로 사용하지 않습니다.
- 원본별 결측·좌표 보정·지역 편향 처리 상태는 [`dataset_roles.md`](dataset_roles.md)의 `11.5 결측·편향 처리 계약 확정`을 기준으로 하며, 미제공 지역을 시설 부재나 감점 근거로 해석하지 않습니다.
- 최종 서비스 역할, 알고리즘 입력과 구현 대기 상태는 같은 문서의 `11.6 최종 서비스 역할과 상태 확정`을 기준으로 합니다.
- V1에 새 데이터를 연결할 때는 `analysis/data-governance/README.md`의 상태 표를 먼저 갱신합니다.

## 5. 비활성 collector 목록 / 팀 확인 필요 항목

| collector | 상태 | 위치 | 팀 확인 필요 사항 |
|---|---|---|---|
| `RunningCourseCollector` | `data_collector.py`에서 주석 처리 | `src/data/collectors/running_collector.py` | V1 기본 적재에서 보류. 활성화 시 `running_score` 결과와 경로 회귀 검증 필요 |
| `SlopeCalculator` | `data_collector.py`에서 주석 처리 | `src/data/collectors/slope_collector.py` | `slope_score` 반영 방식과 running 모드 해석을 함께 검증한 뒤 활성화 |
| 서울 둘레길.csv ↔ `RunningCourseCollector._TRAIL_COORDS` | CSV는 메타데이터, 코드는 좌표 하드코딩 | `src/data/collectors/running_collector.py` | CSV에는 좌표 컬럼이 없어 `_TRAIL_COORDS`를 바로 대체할 수 없음. 단기적으로는 하드코딩 좌표를 유지하고 CSV를 거리/난이도/설명 보강용으로 연결하는 방향이 적절함 |
| street_tree (`전국가로수길정보표준데이터.csv`) | raw-only, collector 미구현 | `CSVSource` | 도보망 근접 검증과 연결 계약은 확정. 50m 후보 Edge의 도로명·연속성 검증 변환기를 구현하기 전까지 `nature_score` 근거로 사용하지 않음 |

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
