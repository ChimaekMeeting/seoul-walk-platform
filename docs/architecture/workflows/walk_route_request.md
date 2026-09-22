# 직접 경로 추천 Workflow

> 상태: Current
> 기준일: 2026-09-20
> 관련 코드: `src/interfaces/api/walk_router.py`, `src/service/route/route_service.py`, `src/route_engine/`
> 검증 상태: 단위 테스트·개발 DB 실제 경로·POI·이력 확인, 모바일 미확인

## 1. 목적과 시작 조건

`POST /api/walk/route`가 위치·모드·프로필에 맞는 보행 경로와 주변 POI를 반환한다.

필요 조건:

- 서버가 NetworkX Graph를 로드했다.
- 서울 경계·수계·도보망·POI가 적재되어 있다.
- 정상 이력 저장에는 유효한 ROUDI access token과 사용자가 필요하다. `Authorization: Bearer`를 우선하고, header가 없을 때만 기존 `access_token` cookie를 사용한다.

지원 모드:

| 모드 | 필수 입력 |
|---|---|
| `circular_random` | `origin`, `mode` |
| `oneway_shortest` | `origin`, `destination`, `mode` |
| `oneway_random` | `origin`, `destination`, `target_km`, `mode` |

`target_km`을 보내는 경우 숫자 또는 숫자 문자열을 허용하며, 숫자로 변환한 값이 유한하고
`0 < target_km <= 10`이어야 한다. `NaN`·양/음의 무한대·boolean·범위 밖 값과 float 변환
범위를 넘는 거대 정수·지수값은 요청 schema 단계에서 HTTP 422로 거절한다. 422의 `detail[]`은
`type`, `loc`, `msg`만 반환하고 입력 원문은 되비추지 않는다. `target_km` 생략·`None`은 기존처럼 허용하지만
`oneway_random`에서는 필수다. 10km 상한은 이 직접 경로 요청 계약에만 적용한다.

현재 `WalkRouteRequest`에는 `profile`이나 가중치 입력 필드가 없다. 직접 API는 서버 기본 가중치로 실행하며, safety/comfort 설문·대화 선호를 섞는 흐름은 챗봇 `RouteExecutor`가 내부 `custom_weights`로 전달할 때만 적용한다.

## 2. 참여 코드

| 코드 | 역할 |
|---|---|
| `walk_schema.py`, `interfaces/validators/` | 좌표·거리·모드·서울 범위 검증 |
| `walk_router.py` | Bearer 우선·cookie fallback으로 access token을 선택하고 요청을 RouteService에 전달 |
| `route_service.py` | 인증, 엔진 선택, POI와 이력 저장 조정 |
| `route_engine/engines/` | 경로 생성 |
| `route_poi_repository.py` | 성공 경로 50m 안의 연결 POI 조회 |
| `repository/user/` | 사용자와 경로 이력 저장 |

## 3. 정상 흐름

```text
요청 검증
→ 서울 경계·수계·고속도로 검증
→ JWT 확인
→ 가까운 Graph Node 탐색
→ 모드별 경로 엔진으로 경로 생성
→ 경로 주변 POI 조회
→ 사용자 이력 저장
→ 응답
```

응답은 `status`, `mode`, `[lat, lon]` 좌표, `total_km`, 선택적 `id`, `nearby_pois`를 포함한다.

## 4. 상태 변화와 결과

- 직접 API는 별도 profile 선택 없이 서버 기본 가중치로 엔진을 실행한다.
- POI 조회 실패는 성공 경로를 실패로 바꾸지 않는다.
- 사용자가 없거나 이력 저장만 실패하면 경로는 반환하고 `id=null`이다.
- 엔진이 내부적으로 생성한 후보 중 품질 평가 기준상 최종 경로 1개만 응답한다. `RouteHistory`도 최종 경로에 대해서만 1개 생성하고 그 `id`를 응답에 포함한다. 내부 비교용 `candidate_features`와 `route_hash`는 최종 이력에 유지한다.

다음은 2026-07-30 당시 profile 입력을 지원하던 코드의 서울시청 `(37.5665, 126.9780)` 개발 DB 관측이다. 현재 `WalkRouteRequest`에는 profile 필드가 없으므로 최신 API의 지원 기능이나 2026-09-20 회귀 검증 결과로 사용하지 않는다.

| 요청 | 상태 | 결과 거리 | 좌표 | 결과 |
|---|---|---:|---:|---|
| 1km `default` | success | 0.66km | 14 | POI 13개, 이력 저장 |
| 1km `convenient` | success | 0.66km | 14 | default와 동일 경로 |
| 1km `accessible` | success | 0.66km | 14 | default와 동일 경로 |
| 3km `default` | success | 2.84km | 55 | 기준 경로 |
| 3km `convenient` | success | 2.84km | 55 | default와 동일 경로 |
| 3km `accessible` | success | 2.58km | 46 | 다른 경로 |

당시 `accessible`이 다른 경로를 생성했고 `convenient`는 이 위치에서 최종 후보를 바꾸지 않았다. 이는 과거 구현의 일회성 결과다.

## 5. 실패·복구

| 조건 | 결과 | 복구 |
|---|---|---|
| 요청 schema 오류 | HTTP 422 | 입력 수정 |
| 서울 Polygon 밖·금지 위치 | HTTP 400 | 출발·도착 위치 수정 |
| access token 없음·만료 | HTTP 200의 인증 상태 응답 | 로그인·토큰 갱신 |
| 잘못된 Authorization 형식 | HTTP 401 `invalid_token`, cookie fallback 없음 | Bearer header 수정 |
| 가까운 Graph Node 없음 | `no_nearest_*` | 좌표·도보망 확인 |
| 경로 없음 | `no_path` 계열 | Graph·엔진 로그 확인 |
| POI 조회 실패 | 경로 유지, 빈 POI | POI 적재·공간 인덱스 확인 |
| 이력 저장 실패 | 경로 유지, `id=null` | 사용자·DB 확인 |
| 예기치 않은 서버 오류 | HTTP 500 공통 안전 메시지 | 사건명·예외 형식 로그로 원인 추적 |

## 6. 검증과 남은 항목

완료:

- 인증 사용자 경로 생성
- 현재 request schema에 삭제된 profile 입력이 다시 노출되지 않음
- 경로 좌표·POI 반환
- 사용자 이력 저장
- `accessible` 경로 변화 확인
- Bearer·cookie·동시 입력·잘못된 header·손상/만료 Bearer 우선순위 회귀 테스트
- 거대 정수·`1e400`·NaN·Infinity의 JSON 입력이 서비스 호출 전 안전한 422가 되는지 확인
- `no_path` 등 기존 업무 상태와 예기치 않은 500 공통 메시지를 분리해 확인

2026-09-20 기준 commit `d2eba6d` 이후 미커밋 worktree를 Windows 로컬 `.venv`에서 TestClient와 mock으로 검증했다. DB 초기화와 Graph 로드는 차단했으며 PostgreSQL·Valkey·외부 API·실제 경로 엔진은 호출하지 않았다. 실제 OpenAPI의 `target_km` 범위, 요청 예시, `AccessTokenBearer`, 400/401/422/500 응답 설명도 자동 테스트로 대조했다.

과거 알고리즘 관측 인계(현재 API 회귀 결과가 아님):

- 1km 요청이 0.66km인데도 `success`
- 3km `accessible` 결과가 2.58km로 10% 허용 오차 밖인데도 `success`
- 목표 거리 허용 범위와 성공 판정 기준 확인 필요

FE 준비 후 검증:

- 모바일 API 연결
- 지도 경로·POI 표시
- GPS 현재 위치
- 실제 야외 산책
