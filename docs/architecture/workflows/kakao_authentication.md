# Kakao 인증 Workflow

> 상태: Current  
> 기준일: 2026-07-27  
> 관련 코드: `src/interfaces/api/login_router.py`, `src/interfaces/api/auth_router.py`, `src/service/user/login_service.py`, `src/service/user/auth_service.py`  
> 검증 상태: Bearer 전환 코드 추적 완료·전환 후 실행 미확인·Kakao 로그인 미확인

## 1. 목적과 시작 조건

Kakao 사용자를 ROUDI 사용자로 연결하고 access/refresh JWT를 발급·검증·폐기하는 흐름이다. Kakao API key와 redirect URI, JWT secret, PostgreSQL, Valkey가 필요하다.

| 시작점 | 입력 | 결과 |
|---|---|---|
| `GET /api/login/kakao` | 없음 | Kakao 인가 URL |
| `GET /api/login/kakao/callback` | 인가 `code` | 사용자·JWT·cookie |
| `POST /api/login/kakao/mobile-login` | Kakao access token | 사용자·JWT body |
| `GET /api/auth/check/access_token` | access Bearer header | 유효 상태 |
| `GET /api/auth/check/refresh_token` | refresh Bearer header | 새 access token body·cookie |
| `POST /api/login/kakao/logout` | 두 cookie | refresh 폐기·cookie 삭제 |

## 2. 참여 코드

| 코드 | 역할 |
|---|---|
| `login_router.py` | 웹·모바일 로그인과 logout HTTP 계약 |
| `login_service.py` | Kakao token/user API 호출과 내부 JWT 생성 조정 |
| `auth_router.py`, `auth_service.py` | JWT 서명·만료와 Valkey token 일치 확인 |
| `user_service.py`, `repository/user/user_repository.py` | 기존 사용자 조회 또는 신규 사용자 저장 |
| `infrastructure/cache/repository/user_repository.py` | `refresh_token:{provider}:{provider_id}` 저장·조회·삭제 |

## 3. 정상 흐름

```text
웹: 인가 URL → Kakao callback code → Kakao access token → Kakao 사용자 정보
모바일: Kakao access token → Kakao 사용자 정보
→ access JWT(60분)·refresh JWT(14일) 생성
→ Valkey에 refresh JWT 저장(TTL 14일)
→ 신규 사용자이면 PostgreSQL users 저장
→ 웹은 body와 cookie, 모바일은 body로 JWT 반환

refresh Bearer header → JWT 검증 → Valkey 값과 일치 확인
→ 새 access JWT 발급 → 응답 body와 access cookie 설정

logout → 유효한 access 또는 refresh에서 사용자 식별
→ Valkey refresh token 삭제 → 두 cookie 삭제
```

## 4. 상태 변화와 결과

- PostgreSQL 사용자는 최초 로그인 때만 추가되며 logout 때 삭제되지 않는다.
- 같은 사용자가 다시 로그인하면 Valkey refresh token만 새 값으로 교체된다.
- 웹 callback은 access cookie를 `HttpOnly=True`, refresh cookie를 `HttpOnly=False`로 설정한다.
- auth 확인 endpoint는 cookie가 아니라 선택적 `Authorization: Bearer` header를 입력으로 받는다.
- refresh endpoint가 새 access token을 body에 포함하고 `HttpOnly=False` access cookie도 설정한다.
- 웹·모바일 로그인 응답 body에도 access/refresh token이 모두 포함된다.
- logout은 token이 없거나 유효하지 않아 사용자를 식별하지 못해도 HTTP 200 / `success`를 반환하고 cookie를 삭제한다.

## 5. 실패·복구

| 조건 | 현재 결과 | 복구 |
|---|---|---|
| access Bearer 없음·만료 | HTTP 200 / `access_expired_token` | refresh 또는 재로그인 |
| access JWT 손상 | HTTP 200 / `invalid_token` | token 폐기 후 재로그인 |
| refresh Bearer 없음·만료 | `refresh_expired_token` | 재로그인 |
| refresh JWT가 Valkey에 없거나 불일치 | `invalid_token` | 재로그인 |
| Kakao code 교환·사용자 조회 실패 | `ValueError`가 router 밖으로 전파 | code·redirect URI·동의 항목 확인 |
| PostgreSQL·Valkey 장애 | 로그인·갱신 실패 | 저장소 복구 후 처음부터 재시도 |

Kakao code는 재사용하지 않는다. logout 후 기존 refresh JWT는 Valkey 검증에 실패하므로 새 로그인으로만 복구한다.

## 6. 검증 결과

2026-07-27 이전 cookie 입력 계약에서는 격리 PostgreSQL·Valkey로 내부 인증을 확인했다. 이후 `origin/dev`의 `a4bcb2f`가 auth 확인 endpoint 입력을 Bearer header로 바꾸고 refresh 응답 body에 access token을 추가했다. merge 후 현재 HTTP 계약은 코드로 대조했지만 실행 검증하지 않았다.

재검증할 항목:

- access Bearer 정상·누락·손상
- refresh Bearer와 Valkey 저장값의 일치·불일치
- refresh 응답 body와 access cookie
- logout 후 refresh 재사용
- 실제 Kakao code 교환과 사용자 조회

기존 `tests/unit/test_auth_service.py`는 현재 `(Provider, provider_id)`·3개 반환값·비동기 refresh 계약을 반영하지 않아 이전 실행에서 21개 중 18개가 실패했다. Bearer 전환 후 자동 테스트는 이번 작업에서 실행하지 않았다.
