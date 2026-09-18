# 경로 그래프 계약

> 상태: Current
> 기준일: 2026-09-19
> 관련 코드: `src/repository/network/graph_repository.py`

## 목적

DB/PostGIS에서 조회한 도보망을 경로 생성 엔진이 사용할 수 있는 NetworkX Graph 형태로 준비합니다.

## 책임

- 주변 도보망 Graph 로드
- 표준 Node·Edge 속성 전달
- 통행 조건 및 차단 tags 기반 필터링
- Graph 직렬화 보조

## 표준 Edge 입력

`GraphRepository._edge_attributes()`는 DB 값을 계산하지 않고 다음 값만 NetworkX
Edge에 전달한다. 이 표는 2026-09-17에 코드와 실제 artifact로 대조한 결과다.

| 구분 | 속성 | 상태 |
|---|---|---|
| 기본 | `link_id`, `length` | 전달됨 |
| 안전·편안 Score | `safety_score`, `accident_score`, `slope_score` | 전달됨(값은 아래 참고) |

(2026-09-19 갱신) 연결 POI 집계(`toilet_count`·`transit_count`·`accessibility_poi_count`)는 더
이상 Edge에 전달되지 않는다. `RoutePoiRepository.get_connected_counts_by_edge()`가 삭제됐고
`GraphRepository._edge_attributes(row)`도 이제 `poi_counts` 인자를 받지 않는 단일 인자
함수다 — 위 표의 `link_id`/`length`/`safety_score`/`accident_score`/`slope_score` 5개가
현재 전달되는 속성 전부다. `GraphArtifactRepository.REQUIRED_EDGE_ATTRIBUTES`도
`frozenset({"link_id", "length"})`로 줄었다.

Node에는 `lon`, `lat`만 전달한다.

POI 집계는 `route_pois.is_route_connected=true`이고 `nearest_edge_id`가 있는
시설만 사용한다.

### 안전·편안 Score의 방향과 결측

| 속성 | 방향 | 범위 |
|---|---|---|
| `safety_score` | 클수록 안전 | 0.0~1.0 |
| `accident_score` | 클수록 위험 | 0.0~1.0 |
| `slope_score` | 클수록 평탄 | 0.0~1.0 |

`walk_edges`의 세 컬럼은 `nullable`이고 server default가 없다. NULL은 "아직
계산하지 않음"이고 `0.0`은 "계산했고 값이 0"이다 — 이 구분을 잃으면 미계산
엣지가 가장 좋은 도로로 읽힌다. `GraphRepository`는 NULL을 `0.0`으로 바꾸지 않고
`None` 그대로 전달하며, 결측 판단은 엣지 단위가 아니라 그래프 단위
커버리지 게이트(`scoring/scoring_engine.py::WeightedEdgeCost.check_coverage`, 2026-09-19 갱신
— `weighted_edge_cost.py`는 삭제되고 `scoring_engine.py`에 합쳐졌다)가 맡는다.

### 현재 적재 상태 (2026-09-17 실측)

운영이 로드하는 `artifacts/walk_graph_v1.pkl`(노드 160,197 / 엣지 223,693) 기준:

- Edge에 실제로 존재하는 속성은 `link_id`, `length`, POI 집계 3종뿐이다.
- POI 집계 3종은 전 엣지에서 값이 `0`이다(min=median=max=0).
- 세 Score는 아직 artifact에 없다. 데이터 적재와 artifact 재빌드가 끝나기 전까지
  커버리지 게이트가 가중 모드를 비활성화하고 거리 전용으로 동작한다.
- `G.graph` 메타는 비어 있고, ALT 휴리스틱은 기동 시 `alt_runtime`이 부착한다.

### 전달하지 않는 값

`raw_link_type_code`, `is_walkable`, `raw_is_*` 플래그, `tags`,
`nature_score`, `running_score`, `landmark_score`, `child_score`,
`park_overlap_ratio`, `convenience_score`, `is_school_zone`,
`is_vehicle_caution`, Node의 `node_type`·`is_underground`·`is_overpass`는
`c5d8c13`("링크 시설 플래그 제거", 2026-08-25)에서 엔티티·리포지토리·수집
파이프라인에서 함께 제거됐다. 되살릴지 여부는 미결이며 이 문서는 현재 코드
기준만 기술한다.

(2026-09-19 갱신) 2026-09-17 시점에 여기 남아 있던 갱신되지 않은 참조 3건은 모두 해소됐다 —
`child_repository.py`(raw SQL이 `edge.is_walkable` 참조)는 파일째 삭제됐고, `graph_filter.py`를
포함한 `src/route_engine/graph/` 폴더 전체가 삭제됐고, `tests/unit/test_graph_repository.py`
(제거 이전 계약을 검증하던 3개 테스트)도 삭제됐다.

## 금지사항

- Layer 또는 Score 계산
- Weights(선호도) 가중치 결정
- 순환·편도 경로 탐색 실행
- FastAPI 또는 챗봇 코드 직접 의존
- 데이터 원본 직접 적재
