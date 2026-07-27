# V1 데이터 재구축

> 상태: Current  
> 기준일: 2026-07-27  
> 관련 코드: `src/data/data_collector.py`, `src/data/collectors/`, `src/repository/network/network_write_repository.py`

이 문서는 PostgreSQL의 V1 도보 네트워크를 최신 원본 전체로 교체하고, 후속 Layer와 서버 메모리 Graph까지 다시 연결하는 절차를 정의합니다. 원본 준비와 일반 적재는 [데이터 적재 실행 가이드](data_ingestion.md), 실제 흐름과 검증 수치는 [V1 데이터 적재 Workflow](../architecture/workflows/v1_data_ingestion.md)를 따릅니다.

## 1. rebuild를 사용하는 조건

다음 경우에만 `rebuild`를 사용합니다.

- V1 기준 원본 전체가 확정되어 기존 NODE·LINK를 교체해야 할 때
- 원본에서 사라진 NODE·LINK도 DB에서 제거해야 할 때
- 기존 Score 초기화를 허용하고 V1 후속 Collector를 다시 실행할 때

개발 중 원본 필드 갱신과 기존 Score 보존이 목적이면 `upsert`를 사용합니다.

| 모드 | 기존 NODE·LINK | 원본에서 사라진 ID | 기존 Score |
|---|---|---|---|
| `upsert` | 동일 ID 갱신·신규 추가 | 유지 | 보존 |
| `rebuild` | 전체 삭제 후 재생성 | 제거 | 기본값으로 초기화 |

## 2. 변경 범위

`--scope v1 --network-mode rebuild`의 현재 변경 순서입니다.

| 순서 | 대상 | 변경 |
|---|---|---|
| 1 | `walk_edges`, `walk_nodes` | 한 transaction에서 전체 교체 |
| 2 | `nature_layer` | `seoul_park_polygon` 유형만 교체 |
| 3 | `walk_edges.park_overlap_ratio` | 전체 0으로 초기화 후 중첩 Edge 갱신 |
| 4 | 서울 행정경계 | 기존 centroid와 다른 Polygon만 추가 |
| 5 | 서울 수계 | 기존 centroid와 다른 Polygon만 추가 |

다음 데이터는 삭제하지 않습니다.

- Docker volume과 RAW 테이블
- 사용자·설문·채팅 세션·경로 이력·배너
- `seoul_park_polygon`이 아닌 기존 `nature_layer`

V1은 `nature_score`, `safety_score`, `child_score`, `landmark_score`, `running_score`를 다시 계산하지 않습니다. rebuild 직후 해당 Score는 기본값이며, 공원 근거는 `park_overlap_ratio`에만 반영됩니다.

## 3. 실행 전 확인

1. 대상 DB가 개발·검증·운영 중 어느 환경인지 확인합니다.
2. 유일한 DB 복사본에서 바로 실행하지 않습니다. 현재 저장소에는 DB backup·restore 자동화가 없습니다.
3. API 서버를 중지하거나 쓰기 시간을 정합니다. 실행 중 서버의 메모리 Graph는 DB 변경을 자동 반영하지 않습니다.
4. 다음 원본을 확인합니다.

```text
src/data/raw/서울시 자치구별 도보 네트워크 공간정보.csv
src/data/raw/서울시 생활권계획 시설(공원) 공간정보.shp
```

공원 Shapefile은 같은 이름의 `.dbf`, `.shx`, `.prj` 등 구성 파일도 함께 있어야 합니다. 서울 행정경계와 수계는 실행 중 OSM에서 조회하므로 네트워크 연결이 필요합니다.

`init_db()`는 빈 격리 DB의 테이블 생성에는 사용할 수 있지만, 기존 DB에서는 Entity에 없는 컬럼을 삭제할 수 있습니다. schema diff와 backup 없이 기존 DB에 실행하지 않습니다.

## 4. 격리 리허설

Compose project 이름을 분리하면 volume 이름도 분리됩니다.

```bash
docker compose -p roudi-workflow up -d db
docker compose -p roudi-workflow ps
```

주의:

- `docker-compose.yml`의 호스트 포트는 5434로 고정되어 있어 기존 DB 컨테이너와 동시에 실행할 수 없습니다.
- 기존 컨테이너를 중지하더라도 volume은 삭제하지 않습니다.
- `docker compose down -v`는 사용하지 않습니다.
- `.env`의 PostgreSQL 접속 대상이 격리 DB인지 확인한 뒤 실행합니다.

빈 격리 DB에서만 테이블을 준비합니다.

```bash
poetry run python -c "from src.entity.base import init_db; init_db()"
```

## 5. V1 rebuild 실행

표준 명령:

```bash
poetry run python -m src.data.data_collector --scope v1 --network-mode rebuild
```

현재 Windows 검증에서는 Poetry가 PATH에 없어 기존 가상환경으로 같은 module entry point를 실행했습니다.

```powershell
.\.venv\Scripts\python.exe -m src.data.data_collector --scope v1 --network-mode rebuild
```

`source_collector --scope v1`은 도보 CSV와 공원 Shapefile을 내려받지 않습니다. 두 원본은 각 Collector가 로컬 파일에서 직접 읽습니다.

## 6. DB 검증

검증용 Compose project가 `roudi-workflow`일 때:

```bash
docker compose -p roudi-workflow exec -T db psql -U postgres -d seoul_walk
```

확인 SQL:

```sql
SELECT
  (SELECT count(*) FROM walk_nodes) AS nodes,
  (SELECT count(*) FROM walk_edges) AS edges,
  (SELECT count(*) FROM nature_layer
   WHERE green_type = 'seoul_park_polygon') AS parks,
  (SELECT count(*) FROM seoul_administrative_boundary) AS boundaries,
  (SELECT count(*) FROM seoul_water_polygons) AS waters;

SELECT
  count(*) FILTER (WHERE s.node_id IS NULL) AS missing_start,
  count(*) FILTER (WHERE t.node_id IS NULL) AS missing_end,
  count(*) FILTER (WHERE NOT e.is_walkable) AS not_walkable,
  count(*) FILTER (WHERE e.park_overlap_ratio > 0) AS park_overlap_edges
FROM walk_edges e
LEFT JOIN walk_nodes s ON s.node_id = e.start_node
LEFT JOIN walk_nodes t ON t.node_id = e.end_node;

SELECT
  min(nature_score), max(nature_score),
  min(safety_score), max(safety_score)
FROM walk_edges;
```

2026-07-27 격리 실행 기준:

| 항목 | 결과 |
|---|---:|
| NODE / LINK | 214,241 / 279,016 |
| 공원 / 경계 / 수계 Polygon | 1,888 / 1 / 411 |
| 누락 start / end 참조 | 0 / 0 |
| 보행 불가 LINK | 253 |
| 공원 중첩 Edge | 13,194 |
| nature·safety score 범위 | 0~0 |

## 7. 서버 Graph 반영

DB 검증 후 서버를 새로 시작합니다.

```bash
poetry run python -m src.main
```

로그에서 다음을 확인합니다.

```text
그래프 로드 완료: 노드 214241개, 엣지 277331개
최대 연결 컴포넌트: 노드 160188개, 엣지 223664개
```

이후 `/api/health`와 대표 직접 경로 요청을 확인합니다. `/api/health`는 PostgreSQL 연결만 검사하므로 Graph 로그와 경로 응답을 함께 봅니다.

## 8. 실패·복구

| 실패 시점 | 현재 transaction 경계 | 복구 |
|---|---|---|
| 원본 파싱·record 생성 | DB 삭제 전 | 원본을 수정하고 전체 명령 재실행 |
| NODE·LINK 삭제·삽입 | 하나의 transaction | 자동 rollback 확인 후 재실행 |
| 공원 Polygon 교체 | 네트워크와 별도 transaction | 공원 원본 확인 후 전체 명령 재실행 |
| 공원 Edge 중첩 갱신 | Polygon 교체와 별도 transaction | Layer·ratio 건수를 확인하고 재실행 |
| 경계·수계 수집 | 앞 단계 commit 후 | 네트워크는 보존하고 전체 명령 재실행 |
| DB 성공·서버 재시작 실패 | DB는 새 상태, Graph 미반영 | 서버 오류 복구 후 다시 시작 |

전체 V1 파이프라인은 하나의 transaction이 아닙니다. NODE·LINK 성공 후 공원·경계·수계가 실패하면 부분 완료 상태입니다. 이전 DB로 정확히 되돌리는 코드 경로는 없으므로 사전 backup 또는 격리 리허설이 복구 기준입니다.

## 9. 완료 기준

- 대상 DB와 원본 snapshot이 식별되어 있다.
- NODE·LINK 참조 누락이 0건이다.
- V1 Layer 건수와 보류 Score 초기화 상태를 확인했다.
- 후속 Collector의 부분 실패가 없다.
- 서버 재시작 후 Graph 로드 로그를 확인했다.
- `/api/health`와 대표 경로 요청이 성공한다.
- 실행 결과와 기준일을 [V1 데이터 적재 Workflow](../architecture/workflows/v1_data_ingestion.md)에 반영한다.
