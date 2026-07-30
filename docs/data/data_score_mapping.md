# 데이터와 알고리즘 입력

> 상태: Current
> 기준일: 2026-07-30
> 관련 코드: `src/data/collectors/`, `src/repository/network/graph_repository.py`, `src/route_engine/scoring/scoring_engine.py`

## 활성 연결

| 원본 | DB 결과 | Graph 입력 | 알고리즘 사용 |
|---|---|---|---|
| 도보 NODE·LINK | `walk_nodes`, `walk_edges` | 길이·형태·통행 속성 | 경로 탐색 |
| CCTV·스마트가로등 | `safety_layer`, `safety_score` | `safety_score` | `safety` 가중치 |
| 어린이보호구역 | `child_layer`, `child_score`, 차량 주의 필드 | `child_score`, `is_vehicle_caution` | 어린이 프로필·차량 주의 페널티 |
| 공원 Polygon | `nature_layer`, `park_overlap_ratio` | `park_overlap_ratio` | `nature` 가중치 |
| 서울 상권 | `convenience_score` | `convenience_score` | `convenience` 가중치 |
| 화장실 | `route_pois` | `toilet_count` | 편의 가점·응답 POI |
| 버스정류소 | `route_pois` | `transit_count` | 편의 가점·응답 POI |
| 리프트·엘리베이터 | `route_pois` | `accessibility_poi_count` | 접근성 가점·응답 POI |

## 비용 계산 계약

양의 근거는 확인된 Edge에만 제한 가점한다. 데이터가 없는 Edge는 감점하지 않는다.

```text
length
× 경사 페널티
× 차량 주의 페널티
× 쾌적도 페널티
÷ 안전·자연·편의·접근성 가점
= custom_score
```

- `slope_score=1`은 평지, `0`은 급경사 방향이다.
- 터널·육교·지하철망·건물 내부는 기본 차단하지 않는다.
- `custom_score`는 음수가 되지 않으며 최소값은 1이다.
- 프로필은 같은 Graph 입력의 가중치만 바꾸고 원본 데이터를 수정하지 않는다.

## 프로필

| 프로필 | 강조 입력 | 사용자 의미 |
|---|---|---|
| `default` | 안전·자연·경사·제한 편의 | 일반 경로 |
| `convenient` | `convenience` | 화장실·대중교통·상권을 고려한 경로 |
| `accessible` | `accessibility`, 경사 | 계단이 불편하거나 유모차를 고려한 이동이 편한 길 |

`accessible`은 엘리베이터·리프트와 경사 데이터에 기반한 선호이며 완전한 무장애·휠체어 경로를 보장하지 않는다.

## 보류 입력

가로수길·보행자우선도로·외부 터널은 후보 Line으로만 저장한다. 둘레길·문화길·자전거도로·지하도는 정상 형상과 의미가 확보될 때까지 Score·Tag·차단 입력으로 사용하지 않는다.

## 변경 완료 조건

새 입력을 추가할 때는 다음 연결을 한 작업에서 확인한다.

```text
원본
→ Entity·Repository
→ Collector
→ WalkEdge 또는 route_pois
→ GraphRepository
→ Weights·Profile·Scoring
→ 경로 API 테스트
```
