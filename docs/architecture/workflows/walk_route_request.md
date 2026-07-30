# 직접 경로 추천 Workflow

> 상태: Current
> 기준일: 2026-07-30
> 관련 코드: `src/interfaces/api/walk_router.py`, `src/service/route/route_service.py`, `src/route_engine/`
> 검증 상태: 단위 테스트·개발 DB 실제 경로·POI·이력 확인, 모바일 미확인

## 1. 목적과 시작 조건

`POST /api/walk/route`가 위치·모드·프로필에 맞는 보행 경로와 주변 POI를 반환한다.

필요 조건:

- 서버가 NetworkX Graph를 로드했다.
- 서울 경계·수계·도보망·POI가 적재되어 있다.
- 정상 이력 저장에는 유효한 `access_token` cookie와 사용자가 필요하다.

지원 모드:

| 모드 | 필수 입력 |
|---|---|
| `circular_random` | `origin`, `mode` |
| `oneway_shortest` | `origin`, `destination`, `mode` |
| `oneway_random` | `origin`, `destination`, `target_km`, `mode` |

프로필은 `default`, `nature`, `safe`, `flat`, `running`, `landmark`, `child`, `convenient`, `accessible`을 지원한다.

## 2. 참여 코드

| 코드 | 역할 |
|---|---|
| `walk_schema.py`, `interfaces/validators/` | 좌표·거리·모드·서울 범위 검증 |
| `walk_router.py` | cookie와 요청을 RouteService에 전달 |
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
→ profile 가중치로 경로 생성
→ 경로 주변 POI 조회
→ 사용자 이력 저장
→ 응답
```

응답은 `status`, `mode`, `[lat, lon]` 좌표, `total_km`, 선택적 `id`, `nearby_pois`를 포함한다.

## 4. 상태 변화와 결과

- 엔진은 공유 Graph 복사본에 `custom_score`를 계산한다.
- POI 조회 실패는 성공 경로를 실패로 바꾸지 않는다.
- 사용자가 없거나 이력 저장만 실패하면 경로는 반환하고 `id=null`이다.
- 성공 경로마다 별도 이력이 생성된다.

2026-07-30 서울시청 `(37.5665, 126.9780)` 개발 DB 관측:

| 요청 | 상태 | 결과 거리 | 좌표 | 결과 |
|---|---|---:|---:|---|
| 1km `default` | success | 0.66km | 14 | POI 13개, 이력 저장 |
| 1km `convenient` | success | 0.66km | 14 | default와 동일 경로 |
| 1km `accessible` | success | 0.66km | 14 | default와 동일 경로 |
| 3km `default` | success | 2.84km | 55 | 기준 경로 |
| 3km `convenient` | success | 2.84km | 55 | default와 동일 경로 |
| 3km `accessible` | success | 2.58km | 46 | 다른 경로 |

`accessible`이 다른 경로를 생성해 프로필 입력의 실제 반영을 확인했다. `convenient`는 이 위치에서 최종 후보를 바꾸지 않았다.

## 5. 실패·복구

| 조건 | 결과 | 복구 |
|---|---|---|
| 요청 schema 오류 | HTTP 422 | 입력 수정 |
| 서울 Polygon 밖·금지 위치 | HTTP 400 | 출발·도착 위치 수정 |
| cookie 없음·만료 | 인증 상태 응답 | 로그인·토큰 갱신 |
| 가까운 Graph Node 없음 | `no_nearest_*` | 좌표·도보망 확인 |
| 경로 없음 | `no_path` 계열 | Graph·엔진 로그 확인 |
| POI 조회 실패 | 경로 유지, 빈 POI | POI 적재·공간 인덱스 확인 |
| 이력 저장 실패 | 경로 유지, `id=null` | 사용자·DB 확인 |

## 6. 검증과 남은 항목

완료:

- 인증 사용자 경로 생성
- 프로필 전달
- 경로 좌표·POI 반환
- 사용자 이력 저장
- `accessible` 경로 변화 확인

알고리즘 인계:

- 1km 요청이 0.66km인데도 `success`
- 3km `accessible` 결과가 2.58km로 10% 허용 오차 밖인데도 `success`
- 목표 거리 허용 범위와 성공 판정 기준 확인 필요

FE 준비 후 검증:

- 모바일 API 연결
- 지도 경로·POI 표시
- GPS 현재 위치
- 실제 야외 산책
