# V1 데이터 재구축

> 상태: Current
> 기준일: 2026-07-30
> 관련 코드: `src/data/data_collector.py`, `src/data/collectors/`, `src/repository/network/`

## 1. 팀원 DB 최신화

오래된 로컬 DB는 목적에 따라 다음 방법으로 최신화한다.

| 목적 | 방법 |
|---|---|
| 최신 데이터로 빠르게 개발 시작 | 최신 SQL 덤프 복원 |
| 데이터 연결 코드 변경·적재 과정 검증 | 공유 RAW로 전체 재구축 |

### 최신 SQL 덤프 복원

일반 개발에서는 재적재가 끝난 최신 DB 덤프를 복원한다.

- 공유 파일: `roudi_v1_2026-07-30.sql`
- 재구축 전에 만든 `backup_before_v1_rebuild.sql`은 최신화에 사용하지 않는다.
- 복원하면 현재 로컬 DB가 교체되므로 필요한 개인 데이터는 먼저 백업한다.
- API 서버를 중지하고 DB·Valkey만 실행한 상태에서 복원한다.

```bash
docker compose up -d

docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < ../roudi_v1_2026-07-30.sql
```

### 공유 RAW로 전체 재구축

데이터 연결 코드나 적재 과정을 검증할 때 사용한다.

1. 이슈 또는 Notion에 안내된 Google Drive에서 버전이 표시된 V1 RAW 묶음을 받는다.
2. 압축을 풀어 파일을 `src/data/raw/`에 배치한다.
3. SHP 자료는 같은 이름의 `.shp`, `.shx`, `.dbf`, `.prj` 파일을 함께 배치한다.
4. 아래의 전체 재구축 절차를 실행한다.

Drive 링크는 저장소 문서에 고정하지 않는다. 저장소에는 공유 묶음 이름과 기준일을 기록하고 실제 링크는 이슈 또는 Notion에서 관리한다.

## 2. 재구축 사용 조건

`rebuild`는 승인 원본 전체로 NODE·LINK와 V1 후속 데이터를 다시 검증할 때 사용한다. 개발 중 필드 확인은 `upsert`를 사용한다.

| 모드 | NODE·LINK | 기존 Score |
|---|---|---|
| `upsert` | 동일 ID 갱신·신규 추가 | 보존 |
| `rebuild` | 전체 교체 | 초기화 후 V1 Collector 재계산 |

## 3. 재구축 실행 전

1. 대상 DB를 확인한다.
2. 현재 DB를 저장할 필요가 있으면 새 백업을 만든다.
3. Docker volume은 삭제하지 않는다.
4. API 서버를 중지하거나 재구축 후 반드시 재시작한다.

백업 예시:

```bash
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > backup_before_rebuild.sql
```

백업은 저장소 밖에 보관한다. 이전 백업은 새 백업 확인 후 개인 복구 필요에 따라 보관하거나 삭제한다.

팀 공유용 최신 SQL 덤프는 전체 재구축과 검증이 끝난 뒤 다음과 같이 만든다.

```bash
docker compose exec -T db sh -c 'pg_dump --clean --if-exists --no-owner --no-privileges --exclude-table-data=users --exclude-table-data=user_preferences --exclude-table-data=route_histories --exclude-table-data=chat_sessions -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > ../roudi_v1_2026-07-30.sql
```

이 명령은 데이터·경로 테이블과 DB 구조를 포함하되 사용자·선호·경로 이력·대화 데이터는 제외한다. 파일 크기가 0보다 큰지 확인한 뒤 Drive에 올린다. SQL 덤프와 RAW 묶음에는 비밀번호·토큰·개인정보를 포함하지 않는다.

## 4. 재구축 실행

```bash
docker compose up -d

./.venv/Scripts/python.exe -c "from src.database.postgresql import health_check; print(health_check())"

./.venv/Scripts/python.exe -c "from src.entity.base import init_db; init_db()"

./.venv/Scripts/python.exe -m src.data.source_collector --scope v1 --refresh-local

./.venv/Scripts/python.exe -m src.data.data_collector --scope v1 --network-mode rebuild
```

POI 단계가 중단된 경우 geography 인덱스를 확인한 후 `RoutePoiCollector`부터 다시 실행할 수 있다.

```bash
./.venv/Scripts/python.exe -c "import logging; logging.basicConfig(level=logging.INFO); from src.data.collectors.route_poi_collector import RoutePoiCollector; RoutePoiCollector().save()"

./.venv/Scripts/python.exe -c "import logging; logging.basicConfig(level=logging.INFO); from src.data.collectors.commercial_collector import CommercialCollector; CommercialCollector().save()"

./.venv/Scripts/python.exe -c "import logging; logging.basicConfig(level=logging.INFO); from src.data.collectors.water_collector import SeoulWaterCollector; SeoulWaterCollector().save()"
```

## 5. 공통 검증

SQL 복원과 RAW 재구축 모두 완료 후 필수 테이블 건수를 확인한다.

```sql
SELECT
  (SELECT COUNT(*) FROM walk_nodes) AS walk_nodes,
  (SELECT COUNT(*) FROM walk_edges) AS walk_edges,
  (SELECT COUNT(*) FROM seoul_administrative_boundary) AS boundaries,
  (SELECT COUNT(*) FROM nature_layer) AS parks,
  (SELECT COUNT(*) FROM safety_layer) AS safety,
  (SELECT COUNT(*) FROM child_layer) AS child,
  (SELECT COUNT(*) FROM edge_feature_layer) AS edge_features,
  (SELECT COUNT(*) FROM route_pois) AS route_pois,
  (SELECT COUNT(*) FROM seoul_water_polygons) AS water;
```

추가 확인:

- LINK 시작·종료 NODE 누락 0건
- 연결 POI의 `nearest_edge_id` 누락 0건
- 필수 Graph 속성이 있는 Edge 존재
- 서버 재시작 후 대표 경로 요청 `success`

관측 건수는 [V1 데이터 적재 Workflow](../architecture/workflows/v1_data_ingestion.md)를 참고하되 고정 상수로 사용하지 않는다.

## 6. 배포용 도보 Graph 빌드

DB 재구축과 공통 검증이 끝난 뒤 배포팀에 전달할 Graph를 만든다. 최종 artifact는 커밋된 코드에서만 생성한다.

```bash
./.venv/Scripts/python.exe -m scripts.build_walk_graph
```

로컬 구현 중 시험 빌드만 다음 옵션을 허용한다. 이 결과는 배포 로더가 거부하므로 전달하지 않는다.

```bash
./.venv/Scripts/python.exe -m scripts.build_walk_graph --allow-dirty
```

출력:

```text
artifacts/walk_graph_v1.pkl
artifacts/walk_graph_v1.manifest.json
artifacts/walk_graph_v1.sha256
```

빌더는 DB의 최종 서비스 Graph를 저장한 뒤 다시 로드하여 노드·엣지 수와 SHA-256을 검증한다. 세 파일을 함께 압축해 Drive로 전달하며 Git에는 커밋하지 않는다.

배포팀은 세 파일을 `artifacts/`에 배치하고 다음 환경변수를 설정한다.

```text
WALK_GRAPH_SOURCE=artifact
WALK_GRAPH_ARTIFACT_PATH=artifacts/walk_graph_v1.pkl
WALK_GRAPH_DATA_VERSION=v1-2026-07-30
WALK_GRAPH_EXPECTED_COMMIT={manifest의 source_commit, 선택}
```

## 7. 실패·복구

| 실패 | 복구 시작점 |
|---|---|
| RAW 적재 | 원본·필터 수정 후 `--refresh-local` |
| NODE·LINK transaction | rollback 확인 후 `rebuild` |
| 후속 Layer·Score | 실패 Collector 재실행 |
| POI 공간 쿼리 장기 실행 | DB 쿼리 취소, geography 인덱스 생성 후 POI 재실행 |
| Graph artifact 검증 실패 | 세 파일의 버전·SHA-256 확인 후 같은 커밋에서 재빌드 |
| DB 성공·서버 실패 | DB 유지, 서버 시작 오류 수정 후 재시작 |
| 새 데이터 전체 폐기 | 확인된 백업으로 복원 |

## 8. 완료 기준

- 대상과 백업 정책이 확인됐다.
- 모든 V1 Collector가 완료됐다.
- DB 참조 무결성과 건수를 확인했다.
- Graph 재로딩과 대표 경로가 성공했다.
- 배포 artifact 세 파일을 같은 커밋에서 생성·검증했다.
- 실행 결과를 Workflow에 기록했다.
