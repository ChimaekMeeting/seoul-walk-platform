# 도보 네트워크 계약

> 상태: Current
> 기준일: 2026-08-20
> 관련 코드: `src/entity/network/`, `src/repository/network/`, `src/route_engine/graph/`

## 1. 책임

서울시 도보 네트워크 NODE·LINK를 경로 엔진의 `WalkNode`, `WalkEdge`, NetworkX Graph로 전달한다. 외부 시설과 공간 데이터는 기본 도보망을 새로 만들지 않고 기존 Edge를 보강한다.

## 2. 입력과 출력

```text
원본 NODE → WalkNode
원본 LINK → WalkEdge
WalkNode + WalkEdge + POI 집계 → NetworkX Graph
```

- 원본 NODE가 없지만 LINK 끝점으로 참조되는 ID는 LINK WKT 끝점으로 보완한다.
- 보행 불가 LINK는 DB에 보존하고 라우팅 Graph에서는 제외한다.
- 동일 노드 쌍의 복수 LINK는 현재 `nx.Graph`에서 한 Edge로 합쳐질 수 있다.

## 3. 표준 속성

| 구분 | Graph Edge 속성 |
|---|---|
| 기본 | `link_id`, `length`, `raw_link_type_code`, `is_walkable` |
| Score | `safety_score`, `nature_score`, `slope_score`, `running_score`, `landmark_score`, `child_score`, `convenience_score` |
| V1 보강 | `park_overlap_ratio`, `is_school_zone`, `is_vehicle_caution` |
| POI 집계 | `toilet_count`, `transit_count`, `accessibility_poi_count` |
| Tag | `tunnel`, `bridge`, `overpass`, `crosswalk`, `elevated`, `subway_network`, `park_green`, `building_inside` |

Tag는 `WalkEdge`의 명시적 필드에서 `GraphRepository` 한 곳이 생성한다.

## 4. 외부 데이터 연결

| 형상 | 연결 기준 |
|---|---|
| 안전·상권 Point | Edge 반경 50m 이내 GiST 공간 조인 집계 |
| 편의·교통·접근성 Point | 50m 이내 최근접 WalkEdge, 가능한 경우 WalkNode |
| 공원 Polygon | Edge와 실제 교차한 길이 비율 |
| 외부 Line | 거리·도로명·연속성 검증 후에만 확정 Tag |

Point를 WalkNode로 만들거나, 유효하지 않은 Line을 임의로 복원하거나, 근접만으로 차단 Tag를 만들지 않는다.

## 5. Graph 생성

개발 모드의 `GraphRepository.load_graph()`는 다음 순서로 서비스 Graph를 만든다.

```text
보행 가능한 NODE·LINK 조회
→ Score·Tag·POI 집계 부착
→ 최대 연결 컴포넌트 선택
→ 막다른 노드 제거
```

배포용 Graph는 이 최종 결과를 `GraphArtifactRepository`로 직렬화한다.

```text
walk_graph_v1.pkl
+ walk_graph_v1.manifest.json
+ walk_graph_v1.sha256
```

`WALK_GRAPH_SOURCE=artifact`이면 서버는 DB에서 NODE·LINK를 다시 조립하지 않고 artifact의 데이터 버전, 선택적 생성 커밋, schema, Python·NetworkX 버전, 노드·엣지 수와 SHA-256을 검증한 뒤 로드한다. 미커밋 코드에서 만든 artifact와 변조된 파일은 배포 모드에서 거부한다.

DB 변경 후 실행 중 Graph는 자동 갱신되지 않으므로 서버를 재시작한다.

## 6. 변경 경계

- 데이터 영역: 원본, DB 필드, Layer·Score·POI와 Graph 속성
- 경로 엔진: 가중치, 차단, 탐색과 성공 판정
- API·챗봇: 프로필 전달과 응답 표현

## 7. 검증

- LINK의 시작·종료 NODE 누락 0건
- Graph 필수 속성 존재
- 보행 불가 LINK 제외
- 연결 POI의 `nearest_edge_id` 무결성
- DB Graph에서 대표 경로 생성 성공
- artifact 저장 후 재로드한 Graph의 노드·엣지 수 일치
- manifest와 checksum의 SHA-256 일치

## 8. 완료 기준

원본→DB→Graph 속성의 단일 매핑이 있고, 보류 데이터를 Graph에 넣지 않으며, 재구축 후 Graph 건수와 대표 경로를 확인하면 완료한다.
