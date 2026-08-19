# 데이터 영역 계약

> 상태: Current
> 기준일: 2026-08-20
> 관련 코드: `src/data/`, `src/entity/network/`, `src/entity/layer/`, `src/repository/network/`, `src/repository/layer/`

## 1. 책임

서울 보행 원본을 검증해 `WalkNode`, `WalkEdge`, Layer, Score, Tag, POI로 변환하고 경로 엔진에 전달한다. 데이터가 없는 지역을 위험하거나 불편한 지역으로 추정하지 않는다.

## 2. 입력

- 서울시 도보 네트워크 NODE·LINK
- 서울 25개 자치구와 공원 Polygon
- 안전·어린이·편의·교통·접근성 원본
- 검증용 Point·Line·Polygon 원본

25개 원본의 사용 여부는 [데이터 역할표](dataset_roles.md)를 단일 기준으로 사용한다.

## 3. 출력

| 출력 | 용도 |
|---|---|
| `walk_nodes`, `walk_edges` | 경로 탐색 기본 그래프 |
| `safety_layer`, `child_layer`, `nature_layer` | Score와 공간 근거 |
| `edge_feature_layer` | 자동 태그 전 검증 후보 |
| `route_pois` | 경로 주변 시설과 Edge 연결 |
| `seoul_administrative_boundary`, `seoul_water_polygons` | 요청 좌표 검증 |
| NetworkX Graph 속성 | 프로필별 경로 비용 계산 |

## 4. 실행 진입점

```text
src.data.source_collector
→ 승인 RAW 적재

src.data.data_collector
→ 도보망·Layer·Score·POI 생성

GraphRepository.load_graph()
→ DB 결과를 NetworkX Graph로 변환
```

실행 명령과 복구 절차는 [데이터 적재](../operations/data_ingestion.md)와 [V1 재구축](../operations/data_rebuild.md)을 따른다.

## 5. 의존 영역

- PostgreSQL/PostGIS
- 로컬 CSV·XLSX·Shapefile
- OSM 수계 조회
- Entity·Repository schema

## 6. 전달 영역

- 경로 엔진: Score, Tag, POI 집계를 Edge 속성으로 전달
- 경로 API: 성공 경로 주변 POI 반환
- 챗봇·설문: 선택한 프로필을 경로 API까지 전달

필드 연결은 [데이터와 알고리즘 입력](data_score_mapping.md), Graph 형식은 [도보 네트워크 계약](walk_network_contract.md)을 따른다.

## 7. 변경 영향

원본 필터, 연결 거리, Score 공식, Graph 속성 중 하나를 바꾸면 RAW 재적재, DB 재구축, Graph 재로딩, 경로 회귀 테스트가 함께 필요하다. 실행 중인 서버의 Graph는 DB 변경을 자동 반영하지 않는다.

## 8. 실패·복구

- 전체 재구축 전 대상 DB를 확인하고 최신 상태를 백업한다.
- NODE·LINK transaction 실패는 rollback 후 전체 명령을 다시 실행한다.
- 후속 Collector 실패는 완료된 앞 단계를 보존하고 실패 단계부터 재실행한다.
- POI 공간 연결이 느리면 geography GiST 인덱스 존재 여부를 먼저 확인한다.
- 복구 상세는 [V1 재구축](../operations/data_rebuild.md)에서 관리한다.

## 9. 검증

- NODE·LINK 참조 무결성
- Layer·Score·POI 건수와 공간 범위
- 연결 POI의 `nearest_edge_id`
- Graph 필수 속성
- `default`, `convenient`, `accessible` 경로 응답

실행 관측값은 [V1 데이터 적재 Workflow](../architecture/workflows/v1_data_ingestion.md)에만 기록한다.

## 10. 완료 기준

- 25개 원본의 역할과 상태가 확정되어 있다.
- 승인 데이터가 DB와 NetworkX Graph까지 연결되어 있다.
- 보류 데이터가 경로 계산에 섞이지 않는다.
- 재구축·복구 명령과 실행 증거가 있다.
- 데이터 계약 변경에 필요한 단위·경로 테스트가 통과한다.
