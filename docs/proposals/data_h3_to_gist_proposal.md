# 데이터 Feature 집계 방식 H3 → GiST(반경 기반) 전환 제안

> 상태: Archive (구현 완료 — §7 참고)
> 기준일: 2026-08-20
> 기준 문서: [data/data_score_mapping.md](../data/data_score_mapping.md), [data/dataset_roles.md](../data/dataset_roles.md), [data/README.md](../data/README.md), [data/walk_network_contract.md](../data/walk_network_contract.md)
> 대상 코드: `src/repository/utils.py`, `src/repository/network/edge_repository.py`, `src/repository/layer/*.py`, `src/data/utils/collector_utils.py`, `src/data/collectors/*.py`

## 1. 목적과 범위

Edge별 Feature Score(`safety_score`, `nature_score`, `convenience_score`, `landmark_score`, `child_score`, `running_score`)를 적재 시점에 계산할 때, 현재는 H3 격자 셀 일치로 Edge와 POI의 근접성을 근사한다. 이를 PostGIS GiST 인덱스 기반의 실제 거리 쿼리(Edge로부터 반경 N m 이내 POI 카운트)로 바꾸는 설계를 조사·제안한다.

이 문서는 조사와 설계 결정 항목까지만 다루며, 이 문서 자체로 코드를 변경하지 않는다.

범위:

- Edge-POI 근접 집계에 쓰이는 H3 변환·매칭 로직 전체
- 위 로직을 호출하는 Collector·Repository 계층의 인터페이스 변경 범위
- 변경에 필요한 PostGIS GiST 인덱스 현황 확인

제외:

- 반경 N 값의 구체적인 수치 결정 (레이어별 튜닝은 팀 판단 필요, §3 참고)
- 실제 코드 구현 — 이 Proposal 승인 후 별도 작업 단위에서 진행
- `frontend/**`

## 2. 현재 방식(H3) 요약과 한계

### 2.1 현재 흐름

1. `src/repository/utils.py:21-22` `RepositoryUtils.lat_lon_to_h3(lat, lon, resolution=9)` — `h3.latlng_to_cell` 직접 호출. h3 의존이 있는 유일한 지점.
2. `src/repository/network/edge_repository.py:53-70` `EdgeRepository.get_link_h3_cells()` — `WalkEdge.geom`의 중심점(centroid) lat/lon을 구한 뒤(`geom_centroid_lat_lon`) h3 셀로 변환해 `(link_id, h3_cell)` 목록을 반환.
3. `src/repository/layer/{safety,commercial,child,nature,landmark,running}_repository.py`의 `get_*_h3_counts()` — 각 레이어 POI 좌표를 h3 셀로 변환해 `{h3_cell: count}` 집계.
   (참조 지점: `safety_repository.py:72`, `commercial_repository.py:25`, `child_repository.py:74`, `nature_repository.py:146`, `landmark_repository.py:56`, `running_repository.py:74`)
4. `src/data/utils/collector_utils.py:17-35` `CollectorUtils.update_edge_scores()` — 2번(Edge→h3_cell)과 3번(h3_cell→count)을 Python에서 dict로 join한 뒤 `log(count+1)/max_log` 정규화, `walk_edges`의 score 컬럼에 UPDATE.
5. 호출부: `src/data/collectors/{safety,commercial,landmark,child,nature,running}_collector.py`의 `.save()`에서 `update_edge_scores(...)` 호출. `src/data/data_collector.py`가 전체 적재 파이프라인을 오케스트레이션.

`src/route_engine/**`(런타임 경로 탐색·cost 계산)은 h3를 참조하지 않는다 — 이미 저장된 score 컬럼 float 값만 읽는다(`scoring_engine.py:52-58` 확인). 따라서 이번 변경은 데이터 적재 파이프라인에 한정된다.

### 2.2 한계

- **격자 경계 근사 오차**: Edge 중심점과 POI가 "같은 h3 셀"이어야 카운트된다. 셀 경계에 걸치면 실제로는 더 가까운 POI가 제외되고, 같은 셀 안의 상대적으로 먼 POI가 포함되는 오차가 발생한다.
- **고정 해상도**: resolution 9(변 길이 약 174 m)가 전 레이어(safety/nature/commercial/landmark/child/running) 공통으로 고정되어, 레이어 특성에 맞는 근접 반경 조정이 불가능하다.
- **Python 레벨 매칭**: `get_link_h3_cells()`와 `get_*_h3_counts()`가 각각 전체 row를 fetch한 뒤 Python dict로 join한다. DB의 공간 인덱스를 활용하지 않는다.

## 3. 변경안(GiST + 반경 N m) — 설계 결정 필요 항목

핵심 아이디어: h3 셀 일치 대신 `ST_DWithin(edge 지오메트리, POI 지오메트리, N)` 기반 실제 거리 쿼리를 SQL에서 직접 수행하고, `walk_edges.geom`과 각 레이어 POI 지오메트리 컬럼에 GiST 인덱스를 걸어 조인 성능을 확보한다.

다음 두 항목은 코드 조사만으로 결정할 수 없어 팀 승인이 필요하다.

| 항목 | 옵션 | 트레이드오프 |
|---|---|---|
| 반경 기준점 | (A) Edge 중심점(point-point 거리) | 기존 h3 구조와 가장 유사하게 포팅 가능. 단, 긴 Edge에서는 중심점과 실제 Edge 위치 간 오차가 커짐 |
| | (B) Edge 선(line) 전체 — `ST_DWithin(edge.geom, poi.geom, N)` | Edge 전 구간 기준으로 정확. 계산량이 (A)보다 약간 크지만 GiST 인덱스로 상쇄 가능 |
| 반경 값 | (A) 전 레이어 공통 단일값 | 기존 h3 resolution 9와 동일한 운용 방식, 튜닝 단순 |
| | (B) 레이어별(safety/nature/commercial 등) 개별값 | POI 밀도·성격이 레이어마다 달라 정확도는 높아지나 운영 파라미터가 늘어남 |

정규화 공식(`log(count+1)/max_log`, `src/data/utils/collector_utils.py:28-29`)은 카운트 산출 방식과 독립적이므로 그대로 유지하는 것을 기본안으로 한다.

## 4. 영향 범위

| 파일 | 변경 내용 |
|---|---|
| `src/repository/utils.py` | `lat_lon_to_h3` 제거, `h3` import 제거 |
| `src/repository/network/edge_repository.py` | `get_link_h3_cells()` 제거 (Edge 중심점의 h3 변환 자체가 불필요해짐) |
| `src/repository/layer/{safety,commercial,child,nature,landmark,running}_repository.py` (6개) | `get_*_h3_counts()` → `walk_edges`와 반경 조인해 `{link_id: count}`를 직접 반환하는 쿼리로 교체 |
| `src/data/utils/collector_utils.py` | `update_edge_scores()`의 h3_cell 매칭 로직을 SQL에서 받은 `{link_id: count}` 결과로 교체. 정규화 로직은 유지 |
| `src/data/collectors/*_collector.py` | `update_edge_scores(...)` 호출 시그니처 영향 최소화 목표 — 내부 카운트 산출 방식만 바뀌므로 호출부 변경은 필요 시에만 |
| DB (PostgreSQL/PostGIS) | `walk_edges.geom`과 각 레이어 POI 지오메트리 컬럼에 GiST 인덱스 존재 여부 확인, 없으면 마이그레이션으로 추가 |
| `src/route_engine/**` | **변경 없음** — h3 미사용 확인됨(§2.1), score 컬럼 값만 읽으므로 영향 없음 |

## 5. 조사 완료 기준

- 현재 H3 흐름(§2.1)의 모든 참조 지점이 코드 대조로 확인되었다.
- 설계 결정이 필요한 항목(§3)이 옵션과 트레이드오프까지 표로 정리되었다.

## 6. 승인과 구현 완료 기준

- 팀이 §3의 두 설계 결정 항목(반경 기준점, 반경 값 단위)을 승인한다.
- 승인된 설계로 §4의 대상 파일 변경을 별도 구현 작업 단위로 진행한다.
- 구현 완료 후 H3를 언급 중인 Current 문서(`data/data_score_mapping.md:39,46`, `data/dataset_roles.md:48`, `data/README.md:76`, 해당 시 `operations/data_ingestion.md`)를 코드에 맞게 갱신한다.
- 이 Proposal 자체는 코드를 변경하지 않으며, 구현은 승인 후 별도 커밋에서 진행한다.

## 7. 구현 결과 (2026-08-20)

§3의 설계 결정은 다음으로 확정·구현되었다.

- **반경 기준점**: (B) Edge 선(line) 전체 — `ST_DWithin(cast(WalkEdge.geom, Geography()), cast({Layer}.geom, Geography()), radius_m)`
- **반경 값**: (A) 전 레이어 공통 단일값, 기본 `radius_m=50`
- **정규화 공식**: 기본안대로 `log(count+1)/max_log` 유지

§4 표 대비 실제 변경:

| 파일 | 실제 변경 |
|---|---|
| `src/repository/utils.py` | `lat_lon_to_h3`, `h3` import 제거 (계획대로) |
| `src/repository/network/edge_repository.py` | `get_link_h3_cells()` 제거, 대신 `get_all_link_ids()` 추가(전체 `link_id` 목록 — `update_edge_scores`가 카운트 0인 Edge도 포함해 정규화하기 위해 필요) |
| `src/repository/layer/{safety,commercial,child,nature,landmark,running}_repository.py` | `get_*_h3_counts()` → `get_*_counts_by_edge(radius_m=50)`로 교체, `{link_id: count}` 반환. `commercial`은 `CsvRaw` 서브쿼리로 동일 좌표 dedup 유지, `nature`는 `osm_raw_id is not null` 필터를 join 조건에 유지 |
| `src/data/utils/collector_utils.py` | `update_edge_scores()`가 `EdgeRepository.get_all_link_ids()` 기준으로 정규화하도록 수정. 파라미터명 `h3_counts` → `edge_counts` |
| `src/data/collectors/*_collector.py` | 계획대로 메서드 호출 이름만 교체(시그니처 안정). `commercial_collector.py`는 docstring·로그 문구도 함께 정리 |
| DB 인덱스 | `walk_edges` + 6개 레이어 + `csv_raw`의 `geom::geography` GiST를 각 Entity `__table_args__`에 `Index(..., postgresql_using="gist")`로 선언(§4 예상과 달리 imperative `CREATE INDEX IF NOT EXISTS`가 아니라 entity 선언 방식 채택). **주의**: `init_table()`은 기존 테이블에 인덱스를 추가하지 않으므로, 이미 존재하는 테이블에는 별도로 수동 `CREATE INDEX`가 필요함(미해결) |
| `src/route_engine/**` | 예상대로 변경 없음 |

계획에 없었으나 함께 정리한 것: `pyproject.toml`·`requirements.txt`의 `h3` 의존성 제거, `Dockerfile`의 `postgresql-16-h3` apt 패키지 제거(활성화된 적 없는 미사용 확장), `tests/conftest.py`의 `h3` 모듈 mock 제거.

**남은 항목**: 이미 존재하는(신규 생성이 아닌) DB에 geography GiST 인덱스를 실제로 적용하는 imperative 코드는 아직 작성하지 않았다. `route_poi_repository.create_spatial_index()`와 동일한 패턴으로 추가 작업 필요.
