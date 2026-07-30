# 서버 시작 Workflow

> 상태: Current
> 기준일: 2026-07-30
> 관련 코드: `src/main.py`, `src/entity/base.py`, `src/interfaces/dependencies.py`, `src/repository/network/graph_repository.py`, `src/repository/network/graph_artifact_repository.py`
> 검증 상태: 개발 DB 실데이터 Graph·루트 API·직접 경로 확인

## 1. 목적과 시작 조건

FastAPI가 요청을 받기 전에 schema, 기본 배너, 메모리 Graph와 경로·챗봇 서비스를 준비한다. PostgreSQL과 적재된 도보망이 필요하다.

## 2. 참여 코드

| 코드 | 역할 |
|---|---|
| `src.main:lifespan()` | startup 순서 |
| `init_db()` | Entity 등록·schema 동기화·배너 seed |
| `init_route_service()` | 환경 설정에 따라 Graph를 선택하고 서비스 생성 |
| `GraphRepository.load_graph()` | DB 도보망을 NetworkX Graph로 변환 |
| `GraphArtifactRepository.load()` | 배포 artifact 검증·재로드 |

## 3. 정상 흐름

```text
개발: WALK_GRAPH_SOURCE=database → DB에서 Graph 생성
배포: WALK_GRAPH_SOURCE=artifact → 빌드된 Graph 검증·로드
→ RouteService·PrewalkOrchestrator 생성
→ API 요청 수신
```

DB 변경은 실행 중 Graph에 자동 반영되지 않으므로 재적재 후 서버를 재시작한다.

## 4. 결과

2026-07-30 개발 DB startup에서 DB Graph 214,241 Node·277,331 Edge를 읽었고, 최대 연결 컴포넌트와 막다른 길 제거 후 160,188 Node·223,664 Edge를 서비스에 전달했다.

`GET /`과 인증된 `POST /api/walk/route`가 성공했다.

2026-07-30 Windows·Python 3.12.13·NetworkX 3.6 시험 빌드에서 같은 서비스 Graph를 64.1MiB `pkl`로 저장했다. DB Graph 생성·저장·재로드는 59.0초, 파일만 검증·재로드하는 데는 2.402초가 걸렸다. 이 결과는 미커밋 코드의 `source_dirty=true` 시험본이므로 배포 인계본으로 사용하지 않는다.

## 5. 실패·복구

| 실패 | 복구 |
|---|---|
| PostgreSQL·schema 실패 | DB·권한 확인 후 재시작 |
| NODE·LINK 없음 | V1 재적재 후 재시작 |
| Graph 조회 실패 | schema·필수 필드·POI 집계 확인 |
| 외부 API·Valkey 실패 | 관련 요청 Workflow에서 복구 |

`init_db()`는 Entity에 없는 컬럼을 삭제할 수 있다. Cloud Run 배포 전에는 schema 반영을 별도 1회 작업으로 분리하고 cold start에서 반복 실행하지 않아야 한다.

## 6. 남은 배포 검증

배포용 Graph 빌드·검증 로더와 로컬 시험은 완료됐다. 커밋 후 최종 artifact 재생성, 컨테이너 메모리와 Cloud Run cold start는 배포 인계 시 검증한다.
