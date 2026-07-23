# V1 데이터 사용 범위

V1에서 실제로 사용하는 데이터와 보류 데이터를 현재 실행 코드 기준으로 정리한다.
별도 registry나 승인 자동화는 두지 않고, `source_collector.py`와
`data_collector.py`의 실제 연결 상태를 기준으로 관리한다.

## 관리 목적

- raw에 존재하는 데이터와 실제 layer/score에 반영되는 데이터를 구분한다.
- V1에서 사용하지 않는 후보 데이터를 서비스 근거로 오해하지 않는다.
- 데이터 출처에서 `walk_edges` 점수까지의 연결을 짧고 명확하게 유지한다.

## 프로젝트 데이터 흐름

```text
원본 파일/API/OSM/Kakao
    ↓
source collector
    ↓
raw table
    ↓
data collector
    ↓
layer table
    ↓
walk_edges score
    ↓
경로 추천/대시보드
```

예외도 있다.

- 도보 네트워크 CSV는 raw table을 거치지 않고 `BaseNetworkCollector`가 직접 읽어 `walk_nodes` / `walk_edges`를 만든다.
- `RunningCourseCollector.save()`는 현재 기본 파이프라인에서 꺼져 있어 공원, 자전거도로, 하천 GeoJSON은 layer 후보지만 비활성이다.

## V1 데이터 상태

| 데이터 | raw 적재 | layer/score 반영 | V1 상태 | 결과 |
|---|---|---|---|---|
| 서울시 도보 네트워크 | 파일 직접 로드 | 활성 | 사용 | `walk_nodes`, `walk_edges` |
| OSM 녹지 | 활성 | 활성 | 사용 | `nature_score` |
| 스마트가로등·CCTV | 활성 | 활성 | 사용 | `safety_score` |
| 사고 다발지역 | 활성 | 활성 | 사용 | `safety_score` |
| 어린이보호구역·놀이시설 | 활성 | 활성 | 사용 | `child_score` |
| TourAPI 관광지·문화시설 | 활성 | 활성 | 사용 | `landmark_score` |
| 실외운동기구 | 활성 | 활성 | 사용 | `running_score` |
| 주요 공원·자전거도로·하천 | 활성 또는 파일 직접 로드 | Collector 기본 실행 꺼짐 | 보류 | `running_score` 후보 |
| DEM 경사 | 별도 파일 | Collector 기본 실행 꺼짐 | 보류 | `slope_score` 후보 |
| 가로수길 | 활성 | Collector 없음 | 보류 | `nature_score` 후보 |
| 서울 둘레길 CSV | 활성 | Collector 직접 연결 없음 | 보류 | 코스 메타데이터 후보 |
| Kakao 주변 장소 | 활성 | layer 연결 없음 | raw-only | 실시간 장소 검색용 후보 |

`source_collector.py`가 raw를 적재한다고 해서 V1 경로 점수에 사용되는 것은 아니다.
`data_collector.py`에서 layer 생성과 edge score 갱신까지 연결된 데이터만 현재
서비스 데이터로 본다.

## 핵심 파일

| 파일 | 역할 |
|---|---|
| `scripts/stage_raw_data.py` | 로컬 raw 파일을 `src/data/raw`로 준비하는 목록 |
| `src/data/source_collector.py` | OSM, Kakao, Public API, CSV/XLSX raw를 적재하는 실행 흐름 |
| `src/data/data_collector.py` | raw를 layer와 score로 변환하는 실행 흐름 |
| `src/data/sources/*` | 원천 데이터를 읽거나 API에서 가져오는 source 코드 |
| `src/data/collectors/*` | raw를 서비스용 layer로 바꾸는 collector 코드 |

## 용어

| 용어 | 의미 |
|---|---|
| raw | 원천에 가까운 데이터. CSV/XLSX, OSM, Kakao, Public API, GeoJSON 등을 포함 |
| raw table | raw를 DB에 저장하는 테이블. `csv_raw`, `osm_raw`, `kakao_raw`, `public_raw` |
| layer | raw를 정제해 서비스에서 쓰기 좋게 만든 공간 데이터. 예: `safety_layer`, `child_layer` |
| score | layer를 기반으로 `walk_edges`에 반영되는 경로 점수. 예: `safety_score` |
| 후보 데이터 | raw에는 있지만 V1 layer/score에 연결하지 않은 데이터 |

## 상태 기준

| status | 의미 |
|---|---|
| active | 현재 기본 파이프라인에서 layer/score에 반영됨 |
| inactive | 연결 코드는 있지만 현재 실행 흐름에서 꺼져 있음 |
| raw_only | raw 적재/로더는 있지만 layer 연결 근거가 없음 |
| direct_load | raw table 없이 파일을 직접 읽어 사용 |

## 관리 원칙

1. 새 데이터는 먼저 raw 파일/API 출처와 실제 사용 목적을 기록한다.
2. V1 테마나 통행 조건에 연결되지 않는 데이터는 추가 구현하지 않는다.
3. source collector에만 있는 데이터와 data collector까지 연결된 데이터를 구분한다.
4. 후보 데이터는 서비스와 대시보드의 확정 근거로 사용하지 않는다.
5. 파일명, query key, collector 명칭은 가능한 한 하나의 canonical 이름으로 맞춘다.
6. raw 대시보드는 active 데이터를 본문으로, inactive/raw-only 데이터는 참고로 분리한다.
7. `walk_edges`에 새 속성을 추가할 때는 원본 → DB → GraphRepository → 알고리즘 연결을 함께 검증한다.
