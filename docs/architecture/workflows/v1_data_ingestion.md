# V1 데이터 적재 Workflow

> 상태: Current  
> 기준일: 2026-07-26  
> 관련 코드: `src/data/source_collector.py`, `src/data/data_collector.py`, `src/data/collectors/`, `src/repository/network/`, `src/repository/layer/`  
> 검증 상태: 코드 추적 완료·격리 DB rebuild와 실데이터 Graph 로딩 확인

## 1. 목적과 시작 조건

V1 승인 데이터를 PostgreSQL/PostGIS에 적재하고, 서버 재시작을 통해 경로 엔진이 사용하는 메모리 Graph에 반영합니다.

필요한 입력은 서울시 도보 네트워크 CSV와 공원 Shapefile입니다. 서울 경계·수계는 OSM에서 수집하므로 네트워크 연결이 필요합니다. 공통 실행 환경은 [백엔드 실행 환경](../../operations/backend_runtime.md), 원본 준비는 [데이터 적재 실행 가이드](../../operations/data_ingestion.md), 전체 교체 절차는 [V1 데이터 재구축](../../operations/data_rebuild.md)을 따릅니다.

## 2. 참여 코드

| 코드 | 역할 |
|---|---|
| `src/data/source_collector.py` | V1 외부·보조 RAW 자동 적재를 건너뜀 |
| `src/data/data_collector.py:collect_v1()` | V1 Collector 실행 순서 제어 |
| `BaseNetworkCollector` | CSV의 NODE·LINK 파싱 |
| `NetworkWriteRepository` | NODE·LINK `upsert` 또는 `rebuild` |
| `ParkPolygonCollector` | 공원 Polygon과 Edge 중첩 비율 저장 |
| `SeoulBoundaryCollector`, `SeoulWaterCollector` | 좌표 검증용 Polygon 저장 |
| `GraphRepository.load_graph()` | DB NODE·LINK를 메모리 Graph로 변환 |

## 3. 정상 흐름

```text
V1 source 수집
→ 외부·보조 RAW 자동 적재 생략
→ 도보 네트워크 CSV 파싱
→ 원본 NODE + 누락 LINK endpoint 보완
→ NODE·LINK upsert 또는 rebuild
→ 공원 Shapefile을 nature_layer에 저장
→ WalkEdge.park_overlap_ratio 갱신
→ 서울 행정 경계 저장
→ 서울 수계 Polygon 저장
→ safety·child·landmark·running 등 보류 Collector 생략
→ 서버 재시작
→ 보행 불가 LINK 제외
→ 최대 연결 컴포넌트 선택·막다른 노드 제거
→ 메모리 NetworkX Graph 반영
```

`upsert`는 기존 Score와 원본에서 사라진 행을 보존합니다. `rebuild`는 NODE·LINK를 한 트랜잭션에서 전체 교체하며 기존 Score를 초기화합니다.

## 4. 상태 변화와 결과

| 결과 | 적재 건수 |
|---|---:|
| 원본 NODE | 212,066 |
| LINK endpoint 보완 NODE | 2,175 |
| 최종 WalkNode | 214,241 |
| WalkEdge | 279,016 |
| 보행 가능 / 불가 LINK | 278,763 / 253 |
| 공원 Polygon | 1,888 |
| 공원 중첩 Edge | 13,194 |
| 원본 공원·녹지 flag Edge | 1,162 |
| 서울 경계 / 수계 Polygon | 1 / 411 |

- 보완 NODE를 포함한 LINK 시작·종료 참조 누락은 각각 0건입니다.
- `raw_is_park_green`과 `park_overlap_ratio`는 별도 근거로 보존됩니다.
- `nature_score`, `safety_score`는 모두 0으로 유지되어 보류 Score가 V1에서 계산되지 않았습니다.
- 실행 중인 서버의 Graph는 DB 변경을 자동 반영하지 않으므로 적재 후 재시작이 필요합니다.

서버 재시작 후 Graph 결과:

| 단계 | Node | Edge |
|---|---:|---:|
| DB에서 보행 가능 LINK 로드 | 214,241 | 277,331 |
| 최대 연결 컴포넌트·막다른 노드 제거 후 | 160,188 | 223,664 |

DB의 보행 가능 LINK 278,763개 중 동일한 노드 쌍을 연결하는 복수 LINK 1,432개가 현재 `nx.Graph`에서 합쳐집니다. 고유 노드 쌍은 277,331개이며 복수 LINK가 있는 노드 쌍은 1,424개입니다.

## 5. 실패·복구

| 조건 | 현재 결과 | 복구 |
|---|---|---|
| 도보망 CSV·공원 Shapefile 누락 또는 형식 오류 | 해당 Collector 실패 | 원본 파일명·컬럼·CRS를 복구하고 재실행 |
| 네트워크 `rebuild` 중 실패 | NODE·LINK 삭제와 삽입 전체 rollback | 오류 수정 후 `rebuild` 재실행 |
| 네트워크 성공 후 공원·경계·수계 실패 | 앞 단계는 이미 commit되어 부분 적재 상태 | 실패 Collector 또는 V1 workflow 재실행 |
| `waterway=riverbank` 응답 없음 | 경고 후 다른 수계 결과로 계속 가능 | `natural=water` 결과와 최종 건수 확인 |
| DB 적재 후 서버 미재시작 | 기존 메모리 Graph 계속 사용 | 서버 재시작 후 Graph 로그 확인 |

이번 실행에서 `waterway=riverbank`는 데이터 없음 경고가 발생했지만 `natural=water`로 최종 수계 411개가 저장됐습니다. 경계·수계 저장 과정에서는 geographic CRS의 centroid 계산 경고가 발생했으며 별도 정확도 검증이 필요합니다.

## 6. 검증 결과

2026-07-26에 기존 DB와 분리된 Compose project `roudi-workflow`에서 실행했습니다.

| 검증 | 결과 |
|---|---|
| 빈 DB에서 `--scope v1 --network-mode rebuild` | 성공 |
| NODE·LINK 건수와 참조 무결성 | 확인 |
| 보행 불가 LINK 253개 보존 | 확인 |
| 공원 Polygon과 중첩 Edge | 1,888 / 13,194 확인 |
| 보류 Score 미계산 | `nature_score=0`, `safety_score=0` 확인 |
| 경계·수계 | 1 / 411 확인 |
| 보류 Collector 생략 | 로그 확인 |
| 서버 재시작과 Graph 반영 | 확인 |
| startup 후 `/api/health` | HTTP 200, `{"ok":true}` |
| 검증 서버 종료 | 완료 |

추가 검증이 필요한 항목:

- 기존 Score가 있는 DB에서 `upsert`가 Score를 보존하는지
- `rebuild` 중간 실패의 실제 rollback 결과
- 동일 노드 쌍의 복수 LINK를 `nx.Graph`에서 합치는 것이 경로 품질에 미치는 영향
- 경계·수계 centroid의 geographic CRS 경고와 H3 결과 정확도
