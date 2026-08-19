# 데이터 적재

> 상태: Current
> 기준일: 2026-08-20
> 관련 코드: `src/data/source_collector.py`, `src/data/data_collector.py`

## 1. 목적

V1 승인 원본을 RAW에 저장하고 도보망·Layer·Score·POI로 변환한다. 원본별 사용 여부는 [데이터 역할표](../data/dataset_roles.md)를 따른다.

## 2. 실행 전 확인

- PostgreSQL/PostGIS와 Valkey 컨테이너가 실행 중이다.
- `.env`가 개발 DB를 가리킨다.
- Shapefile의 `.shp`, `.shx`, `.dbf`, `.prj`가 함께 있다.
- 전체 재구축이면 최신 DB 백업과 복구 대상을 확인한다.

```bash
docker compose up -d
docker compose ps
```

## 3. Schema 반영

기존 DB에서는 backup과 schema diff를 확인한 후 한 번만 실행한다.

```bash
./.venv/Scripts/python.exe -c "from src.entity.base import init_db; init_db()"
```

`init_db()`는 Entity에 없는 컬럼을 삭제할 수 있으므로 운영 서버 cold start에서 반복 실행하지 않는다.

## 4. 승인 RAW 적재

기존 RAW를 유지하며 없는 태그만 적재한다.

```bash
./.venv/Scripts/python.exe -m src.data.source_collector --scope v1
```

원본 파일·필터·좌표 보정 코드가 바뀌었다면 승인 태그를 현재 결과로 교체한다.

```bash
./.venv/Scripts/python.exe -m src.data.source_collector --scope v1 --refresh-local
```

## 5. 서비스 데이터 적재

개발 중 NODE·LINK를 갱신하고 기존 값을 보존한다.

```bash
./.venv/Scripts/python.exe -m src.data.data_collector --scope v1 --network-mode upsert
```

최종 검증에서 NODE·LINK와 후속 결과를 다시 만든다.

```bash
./.venv/Scripts/python.exe -m src.data.data_collector --scope v1 --network-mode rebuild
```

V1 실행 순서:

```text
도보망
→ 자치구 경계
→ 공원 Polygon
→ 안전·어린이 Layer와 Score
→ 외부 Line 후보
→ 편의·교통·접근성 POI
→ 상권 편의 Score
→ 수계 Polygon
```

## 6. 연결 기준

- 안전·어린이·상권: Edge 반경 50m 이내 GiST 공간 조인 집계
- 화장실·버스정류소·리프트·엘리베이터: 50m 이내 WalkEdge
- 공원: Polygon과 Edge의 실제 교차 길이
- 가로수길·보행자우선도로·외부 터널: 후보 Layer까지만 저장

POI 연결·안전/어린이/상권/자연/랜드마크/러닝 Score 집계 전 다음 geography GiST 인덱스가 있어야 한다.

```text
idx_route_pois_geog
idx_walk_edges_geog
idx_walk_nodes_geog
idx_safety_layer_geog
idx_child_layer_geog
idx_running_layer_geog
idx_nature_layer_geog
idx_landmark_layer_geog
idx_csv_raw_geog
```

`idx_route_pois_geog`·`idx_walk_edges_geog`·`idx_walk_nodes_geog`는 `RoutePoiRepository.create_spatial_index()`가 POI 연결 시점에 직접 생성한다. 나머지(Score 집계용) 6개는 각 Entity의 `__table_args__`에 선언되어 있어 테이블을 새로 만들 때만 자동 생성되고, 이미 존재하는 테이블에는 자동 반영되지 않는다(`init_table()`은 기존 테이블의 컬럼만 diff하고 인덱스는 다루지 않는다). 기존 DB에 적용하려면 `CREATE INDEX IF NOT EXISTS idx_{table}_geog ON {table} USING GIST ((geom::geography))`를 테이블별로 직접 실행해야 한다.

## 7. 정상 기준

- 명령이 완료 로그와 함께 종료된다.
- NODE·LINK 참조 누락이 없다.
- 승인 Layer·Score·POI가 생성된다.
- 서버 재시작 후 Graph 로드와 대표 경로 요청이 성공한다.

실제 실행 건수는 [V1 데이터 적재 Workflow](../architecture/workflows/v1_data_ingestion.md)에서 관리한다.

## 8. 실패 시

- RAW 교체 실패: transaction rollback 확인 후 `--refresh-local` 재실행
- NODE·LINK 실패: rollback 확인 후 `rebuild` 전체 재실행
- POI 지연: 실행 쿼리 취소 후 geography 인덱스 확인
- 후속 Collector 실패: 완료된 DB를 보존하고 실패 Collector부터 재실행
- DB 성공·Graph 미반영: 서버 재시작

전체 복구 절차는 [V1 재구축](data_rebuild.md)을 따른다.
