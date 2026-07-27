# 직접 경로 추천 Workflow

> 상태: Current  
> 기준일: 2026-07-27  
> 관련 코드: `src/interfaces/api/walk_router.py`, `src/interfaces/schema/walk_schema.py`, `src/service/route/route_service.py`, `src/route_engine/`  
> 검증 상태: 코드 추적 완료·격리 DB 로컬 통합 확인

## 1. 목적과 시작 조건

`POST /api/walk/route`가 사용자 위치와 요청 모드에 맞는 보행 경로를 반환하는 흐름이다.

시작 전 다음 조건이 필요하다.

- [서버 시작 Workflow](server_startup.md)가 완료되어 `RouteService`가 메모리 Graph를 보유한다.
- PostgreSQL에 서울 행정경계, 수계 Polygon과 보행 노드가 적재되어 있다.
- 정상 경로 요청에는 유효한 `access_token` cookie와 해당 토큰의 사용자가 필요하다.

| 모드 | 필수 입력 | 현재 엔진 |
|---|---|---|
| `circular_random` | `origin`, `mode` | `CircularBeamEngine` |
| `oneway_shortest` | `origin`, `destination`, `mode` | `OnewayDijkstraEngine` |
| `oneway_random` | `origin`, `destination`, `target_km`, `mode` | `OnewayBeamEngine` |

`target_km`은 0보다 크고 10km 이하여야 한다. `oneway_random`에서는 직선거리보다 짧거나 목적지가 목표 거리에 비해 지나치게 가까운 요청도 거부한다. `circular_random`에 전달된 `destination`은 스키마에서 제거된다.

## 2. 참여 코드

| 순서 | 코드 | 역할 |
|---|---|---|
| 1 | `src/interfaces/schema/walk_schema.py` | 좌표·거리·모드 조합을 검증한다. |
| 2 | `src/interfaces/api/walk_router.py` | cookie를 받고 PostgreSQL 좌표 검증 후 서비스를 호출한다. |
| 3 | `src/interfaces/validators/` | 서울 Polygon, 수계, 보행 노드 근접 여부를 확인한다. |
| 4 | `src/service/route/route_service.py` | JWT 확인, 최근접 노드 확인, 모드별 엔진 선택과 이력 저장을 조정한다. |
| 5 | `src/route_engine/engines/` | 메모리 Graph에서 실제 경로를 생성한다. |
| 6 | `src/repository/user/` | 토큰 사용자를 조회하고 성공 경로를 `RouteHistory`로 저장한다. |

Graph의 적재·필드 계약은 [Graph 계약](../../route_engine/graph_contract.md)에서 관리한다.

## 3. 정상 흐름

```text
POST /api/walk/route
→ Pydantic: 좌표·서울 bbox·거리·모드 조합 검증
→ PostgreSQL: 서울 행정경계 Polygon 포함 여부 확인
→ PostgreSQL: 수계 위 좌표이면 100m 이내 보행 노드로 Snap
→ 원좌표를 유지한 경우 100m 이내 보행 노드 존재 여부 확인
→ access_token 서명·만료 확인
→ 메모리 Graph에서 출발·도착 최근접 노드 확인
→ 모드별 엔진 생성·실행
→ success이면 토큰 사용자 조회 후 RouteHistory 저장
→ WalkRouteResponse 반환
```

현재 구현에서는 PostgreSQL 좌표 검증이 JWT 검사보다 먼저 실행된다. 따라서 인증이 없는 요청도 좌표가 스키마 검증을 통과하면 DB 조회까지 수행한다.

## 4. 상태 변화와 결과

- 경로 탐색은 startup 때 적재한 메모리 Graph를 읽는다. 각 엔진은 Graph 복사본에 `custom_score`를 계산하므로 공유 Graph를 직접 수정하지 않는다.
- 응답은 `status`, `mode`, `[lat, lon]` 좌표 배열, `total_km`, 선택적 `id`를 포함한다.
- `status=success`이고 토큰에 해당하는 사용자가 존재할 때만 `route_histories`에 저장하고 응답 `id`를 채운다.
- 이력 저장만 실패하면 경로 응답은 유지되고 `id`는 `null`이다.

2026-07-27 격리 DB의 동일 출발지와 목적지로 확인한 결과:

| 모드 | HTTP/상태 | 좌표 수 | 결과 거리 | 이력 ID |
|---|---|---:|---:|---:|
| `circular_random` | 200 / `success` | 40 | 2.01km | 1 |
| `oneway_shortest` | 200 / `success` | 33 | 1.14km | 2 |
| `oneway_random` | 200 / `success` | 47 | 1.97km | 3 |

순환 경로의 첫 좌표와 마지막 좌표는 같았다. 두 편도 경로는 요청 목적지에 가장 가까운 Graph 노드에서 끝났다.

## 5. 실패·복구

| 실패 지점 | 결과 | 복구 | 실행 확인 |
|---|---|---|---|
| 좌표·거리·필수 목적지 스키마 오류 | HTTP 422 | 요청 값을 고쳐 재요청한다. | 목적지 누락·bbox 밖 |
| bbox는 통과했지만 서울 Polygon 밖 | HTTP 400 | 서울 내부 좌표로 재요청한다. | 확인 |
| cookie 없음 | HTTP 200 / `access_expired_token` | 로그인 또는 토큰 갱신 후 재요청한다. | 확인 |
| 위조·손상된 JWT | HTTP 200 / `invalid_token` | cookie를 폐기하고 다시 로그인한다. | 확인 |
| 가까운 출발·도착 노드 없음 | HTTP 200 / `no_nearest_*_node` | 좌표 또는 NODE 적재 상태를 확인한다. | 미확인 |
| 엔진이 경로를 만들지 못함 | HTTP 200 / `no_path` 등 | 연결 Graph와 엔진 로그를 확인한다. | 미확인 |
| 수계 위 100m 안에 보행 노드 없음 | HTTP 400 | 보행 가능한 위치를 다시 선택한다. | 미확인 |
| 예상하지 못한 예외 | HTTP 500 | traceback과 요청을 확인한다. | 미확인 |
| RouteHistory 저장 실패 | 경로 반환, `id=null` | DB 복구 후 재요청한다. | 미확인 |

스키마·좌표·인증·엔진 실패는 이력을 만들지 않는다. 경로 이력은 성공 결과마다 별도 transaction으로 저장되므로 중복 재요청 시 새 이력이 추가된다.

## 6. 검증 결과

기존 개발 DB와 분리한 Compose project `roudi-workflow`에서 검증했다. DB에는 NODE 214,241건과 LINK 279,016건이 있었고, 최대 연결 컴포넌트 선택 후 메모리 Graph는 160,188노드·223,664엣지였다. 서울시청 부근 `(37.5665, 126.9780)`에서 광화문 부근 `(37.5759, 126.9768)`으로 요청했으며, 테스트 사용자와 JWT는 Kakao 외부 호출 없이 만들었다.

정상 요청은 세 엔진 모두 HTTP 200 / `success`였고, 서버 로그의 선택 엔진과 응답 모드가 일치했다. DB에는 응답 `id`와 일치하는 이력 3건만 저장되었다.

실패 요청 후에도 이력은 3건으로 유지됐다. 아직 직접 실행하지 않은 분기는 수계 좌표 Snap, 보행 노드가 없는 위치 차단, `no_nearest_*_node`, `no_path`, profile별 점수 변화와 이력 저장 장애다.
