# V1 데이터 적재 Workflow

> 상태: Current
> 기준일: 2026-07-30
> 관련 코드: `src/data/source_collector.py`, `src/data/data_collector.py`, `src/data/collectors/`
> 검증 상태: 개발 DB 전체 재구축·Graph 로드·대표 경로 확인

## 1. 목적과 시작 조건

승인 RAW를 PostgreSQL/PostGIS의 도보망·Layer·Score·POI로 변환하고 서버 Graph에 반영한다.

시작 조건:

- 대상 DB와 백업 정책 확인
- V1 원본과 Shapefile sidecar 준비
- PostgreSQL/PostGIS 실행
- [데이터 적재](../../operations/data_ingestion.md)와 [V1 재구축](../../operations/data_rebuild.md) 확인

## 2. 참여 코드

| 순서 | 코드 | 결과 |
|---:|---|---|
| 1 | `source_collector --scope v1` | 승인 CSV·XLSX RAW |
| 2 | `BaseNetworkCollector` | `walk_nodes`, `walk_edges` |
| 3 | `SeoulBoundaryCollector` | 25개 자치구 경계 |
| 4 | `ParkPolygonCollector` | 공원 Polygon, `park_overlap_ratio` |
| 5 | `SafetyCollector`, `ChildCollector` | 안전·어린이 Layer와 Score |
| 6 | `EdgeFeatureCollector` | 외부 Line 검증 후보 |
| 7 | `RoutePoiCollector` | 편의·교통·접근성 POI 연결 |
| 8 | `CommercialCollector` | `convenience_score` |
| 9 | `SeoulWaterCollector` | 수계 Polygon |
| 10 | `GraphRepository` | NetworkX Graph |

## 3. 정상 흐름

```text
Schema 반영
→ 승인 RAW 교체
→ NODE·LINK rebuild
→ 자치구·공원
→ 안전·어린이
→ 외부 Line 후보
→ POI
→ 상권
→ 수계
→ 서버 재시작
→ Graph·경로 확인
```

## 4. 상태 변화와 결과

2026-07-30 Windows·Docker 개발 DB 관측값이다. 원본 갱신 시 달라질 수 있으며 고정 기대값으로 사용하지 않는다.

| DB 결과 | 건수 |
|---|---:|
| `walk_nodes` | 214,241 |
| `walk_edges` | 279,016 |
| 자치구 경계 | 25 |
| 공원 Polygon | 1,886 |
| `safety_layer` | 45,017 |
| `child_layer` | 1,466 |
| 외부 Line 후보 | 1,123 |
| `route_pois` | 16,435 |
| 수계 Polygon | 411 |

| WalkEdge 반영 | 건수 |
|---|---:|
| `safety_score > 0` | 267,822 |
| `child_score > 0` | 67,319 |
| `convenience_score > 0` | 267,780 |
| `park_overlap_ratio > 0` | 13,193 |
| 차량 주의 Edge | 1,392 |

POI 연결 결과:

| 유형 | 전체 | 50m 이내 Edge 연결 |
|---|---:|---:|
| 주요 공원 | 132 | 81 |
| 화장실 | 4,415 | 4,237 |
| 버스정류소 | 11,253 | 11,219 |
| 리프트 | 83 | 83 |
| 엘리베이터 | 552 | 552 |

연결 상태인데 `nearest_edge_id`가 없는 POI는 0건이었다. 일부 긴 Edge에서는 50m 이내 Node가 없어 `nearest_node_id`가 비어 있지만 Edge 연결은 유효하다.

서버 Graph 관측:

| 단계 | Node | Edge |
|---|---:|---:|
| DB의 보행 가능 링크 로드 | 214,241 | 277,331 |
| 최대 컴포넌트·막다른 길 제거 후 | 160,188 | 223,664 |

## 5. 실패·복구

최초 POI 연결은 `geom::geography` 거리 비교에 맞는 인덱스가 없어 PostgreSQL CPU를 장시간 사용했다. 실행 쿼리를 취소하고 다음 인덱스를 만든 뒤 POI 단계부터 재실행했다.

```text
idx_route_pois_geog
idx_walk_edges_geog
idx_walk_nodes_geog
```

수계의 `waterway=riverbank`는 데이터 없음 경고가 발생했지만 `natural=water` 결과로 411개 Polygon을 저장했다. geographic CRS centroid 경고는 후속 정확도 검토 항목이다.

복구 기준:

- NODE·LINK 실패: transaction rollback 후 `rebuild`
- 후속 Collector 실패: 실패 단계부터 재실행
- DB 완료·Graph 미반영: 서버 재시작
- 전체 폐기: 확인된 백업 복원

## 6. 검증 결과

- NODE·LINK와 V1 후속 Collector 완료
- 서울 자치구 25개 확인
- 연결 POI Edge 참조 무결성 확인
- Graph 필수 데이터 로드 확인
- `default`, `convenient`, `accessible` 직접 경로 생성 확인
- 사용자 경로 이력과 주변 POI 응답 확인

모바일 GPS·지도·야외 산책 검증은 FE 앱 준비 후 진행한다.
