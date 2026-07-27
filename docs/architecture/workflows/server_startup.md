# 서버 시작 Workflow

> 상태: Current  
> 기준일: 2026-07-26  
> 관련 코드: `src/main.py`, `src/entity/base.py`, `src/interfaces/dependencies.py`, `src/repository/network/graph_repository.py`
> 검증 상태: 코드 추적 완료·빈 Graph 로컬 통합 확인·실데이터 Graph 미검증

## 1. 목적과 시작 조건

FastAPI가 요청을 받기 전에 PostgreSQL schema, 기본 배너, 메모리 Graph와 경로·챗봇 서비스를 준비합니다.

시작하려면 프로젝트 Python 환경과 PostgreSQL 연결이 필요합니다. 실제 경로를 생성하려면 `walk_nodes`와 `walk_edges`가 적재되어 있어야 합니다. Poetry·Python·Docker 준비 방법은 [백엔드 실행 환경](../../operations/backend_runtime.md)을 따릅니다.

## 2. 참여 코드

| 코드 | 역할 |
|---|---|
| `src/main.py:lifespan()` | startup 순서 제어 |
| `src/config/logging.py:setup_logging()` | stdout 로그 설정 |
| `src/entity/base.py:init_db()` | Entity 등록, schema 동기화, 배너 seed |
| `src/interfaces/dependencies.py:init_route_service()` | Graph와 경로·챗봇 서비스 생성 |
| `src/repository/network/graph_repository.py:load_graph()` | NODE·LINK를 NetworkX Graph로 변환 |

## 3. 정상 흐름

```text
Uvicorn이 src.main:app 로드
→ FastAPI lifespan 시작
→ 로깅 설정
→ Entity 등록·DB schema 동기화
→ 기본 배너 seed
→ walk_nodes·walk_edges로 Graph 생성
→ RouteService 생성
→ PrewalkOrchestrator와 LangGraph 생성
→ lifespan의 yield 도달
→ API 요청 수신
```

## 4. 상태 변화와 결과

- PostgreSQL에 Entity 기준 테이블이 생성·동기화됩니다.
- `banners`가 비어 있으면 기본 배너 6개가 저장됩니다.
- DB의 NODE·LINK가 프로세스 메모리의 `networkx.Graph`로 복사됩니다.
- `RouteService`와 `PrewalkOrchestrator`가 모듈 전역 singleton에 저장됩니다.
- DB의 NODE·LINK·Score를 변경해도 실행 중인 Graph는 자동 갱신되지 않습니다. 현재 반영 지점은 서버 재시작입니다.

## 5. 실패·복구

| 조건 | 현재 결과 | 복구 |
|---|---|---|
| PostgreSQL 연결·schema 변경 실패 | startup 실패, API 수신 불가 | DB·권한·schema 확인 후 서버 재시작 |
| NODE·LINK가 없음 | 빈 Graph 경고 후 startup 계속 | V1 데이터 적재 후 서버 재시작 |
| Graph 조회 실패 | 경로·챗봇 서비스 생성 전 startup 실패 | NODE·LINK schema와 DB 조회 복구 후 재시작 |
| Valkey·외부 API 중단 | startup에서는 실제 연결하지 않음 | 요청 workflow에서 별도 처리 |

`init_db()`는 Entity에 없는 기존 컬럼을 startup 중 삭제할 수 있습니다. 기존 DB에서는 backup과 schema diff 없이 실행하지 않습니다.

## 6. 검증 결과

2026-07-26에 기존 DB와 분리된 Compose project `roudi-workflow`로 확인했습니다.

| 검증 | 결과 |
|---|---|
| 새 PostgreSQL에서 startup | 성공 |
| 애플리케이션 테이블 생성 | 18개 |
| 기본 배너 seed | 6개 |
| 빈 Graph | node 0개·edge 0개, startup 성공 |
| `GET /` | HTTP 200, 서비스 메시지 반환 |
| `GET /api/health` | HTTP 200, `{"ok":true}` |
| 검증 서버 종료 | 완료 |
| V1 실데이터 Graph | 미검증 |
| PostgreSQL 장애 startup | 미검증 |
| 기존 schema 변경·복구 | 미검증 |

현재 완료 수준은 “격리 PostgreSQL과 빈 Graph를 사용한 startup 확인”입니다.
