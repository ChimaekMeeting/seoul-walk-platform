# Data Governance

팀 단위로 데이터 관리 방식이 흔들리지 않도록, 프로젝트의 데이터 흐름과 용어를 정리한다.

## 왜 따로 관리하는가

현재 프로젝트에는 raw 파일, API 수집 데이터, registry, source collector, data collector, layer가 함께 존재한다. 이 구조를 통일해서 이해하지 않으면 다음 문제가 생긴다.

- 파일은 있는데 실제 layer에 안 쓰이는 데이터를 사용 중이라고 오해할 수 있다.
- `approved=false` draft 데이터를 서비스 근거로 착각할 수 있다.
- Kakao처럼 raw 적재는 되지만 layer에 안 쓰이는 데이터를 대시보드 본문에 넣을 수 있다.
- 팀원마다 raw, layer, score의 의미를 다르게 해석할 수 있다.

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

## 핵심 파일

| 파일 | 역할 |
|---|---|
| `src/data/registry.yaml` | 공식 데이터 목록과 승인 여부, raw/layer/score 연결을 적는 데이터 계약서 |
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
| registry | 어떤 데이터를 공식적으로 사용할지 정의하는 계약서 |
| draft | 후보 데이터. `approved=false`이면 서비스/대시보드 본문 근거로 쓰지 않는다 |

## 상태 기준

| status | 의미 |
|---|---|
| active | 현재 기본 파이프라인에서 layer/score에 반영됨 |
| inactive | 연결 코드는 있지만 현재 실행 흐름에서 꺼져 있음 |
| draft | 승인 전 후보 데이터 |
| raw_only | raw 적재/로더는 있지만 layer 연결 근거가 없음 |
| direct_load | raw table 없이 파일을 직접 읽어 사용 |

## 관리 원칙

1. 새 데이터를 추가할 때는 먼저 raw 파일/API 출처를 기록한다.
2. 실제 서비스나 대시보드 본문에 쓰려면 `registry.yaml`에 dataset을 명확히 등록한다.
3. `approved=false` 데이터는 후보로만 다루고, layer/score 근거로 말하지 않는다.
4. source collector에만 있는 데이터와 data collector까지 연결된 데이터를 구분한다.
5. 파일명, dataset id, collector tag는 가능한 한 하나의 canonical 이름으로 맞춘다.
6. raw 대시보드는 active 데이터를 본문으로, inactive/draft/raw-only 데이터는 참고 섹션으로 분리한다.

