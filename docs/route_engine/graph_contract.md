# 경로 그래프 계약

> 상태: Current
> 기준일: 2026-07-30
> 관련 코드: `src/route_engine/graph/`, `src/repository/network/graph_repository.py`

## 목적

DB/PostGIS에서 조회한 도보망을 경로 생성 엔진이 사용할 수 있는 NetworkX Graph 형태로 준비합니다.

## 책임

- 주변 도보망 Graph 로드
- 표준 Node·Edge 속성 전달
- 통행 조건 및 차단 tags 기반 필터링
- Graph 직렬화 보조

## 표준 Edge 입력

`GraphRepository`는 DB 값을 계산하지 않고 다음 값을 NetworkX Edge에 전달한다.

| 구분 | 속성 |
|---|---|
| 기본 | `link_id`, `length`, `raw_link_type_code`, `is_walkable` |
| 기존 Score | `safety_score`, `nature_score`, `slope_score`, `running_score`, `landmark_score`, `child_score` |
| V1 데이터 | `park_overlap_ratio`, `convenience_score`, `is_school_zone`, `is_vehicle_caution` |
| 연결 POI 집계 | `toilet_count`, `transit_count`, `accessibility_poi_count` |
| 검증된 원본 Tag | `tunnel`, `bridge`, `overpass`, `crosswalk`, `elevated`, `subway_network`, `park_green`, `building_inside` |

POI 집계는 `route_pois.is_route_connected=true`이고 `nearest_edge_id`가 있는
시설만 사용한다. 가로수길·보행자우선도로·외부 터널 후보 Line은 검증된
WalkEdge Tag가 아니므로 그래프에 전달하지 않는다.

## 금지사항

- Layer 또는 Score 계산
- Profile 가중치 결정
- 순환·편도 경로 탐색 실행
- FastAPI 또는 챗봇 코드 직접 의존
- 데이터 원본 직접 적재
