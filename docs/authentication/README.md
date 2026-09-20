# 인증·Kakao 로그인 계약

> 상태: Current  
> 기준일: 2026-09-20
> 관련 코드: `src/interfaces/api/auth_router.py`, `src/interfaces/api/login_router.py`, `src/service/user/auth_service.py`, `src/service/user/login_service.py`

## 1. 책임

이 영역은 Kakao 사용자를 ROUDI 사용자로 연결하고 내부 access·refresh JWT를 생성·검증·폐기한다.

- 웹 Kakao OAuth 인가 URL과 callback 처리
- 모바일 Kakao access token 로그인
- 내부 JWT 생성·서명·만료 검증
- refresh token의 Valkey 일치 검증
- 로그인 사용자 생성과 refresh token 교체
- logout 시 refresh token과 cookie 폐기

사용자 프로필·설문·경로 이력의 조회·변경은 사용자 영역 책임이다. Kakao 장소 검색은 지도·챗봇 영역에서 관리한다.

## 2. 입력

| 진입점 | 입력 |
|---|---|
| `GET /api/login/kakao` | 없음 |
| `GET /api/login/kakao/callback` | Kakao 인가 `code` query |
| `POST /api/login/kakao/mobile-login` | body의 Kakao `access_token` |
| `GET /api/auth/check/access_token` | `Authorization: Bearer {access_token}` |
| `GET /api/auth/check/refresh_token` | `Authorization: Bearer {refresh_token}` |
| `POST /api/login/kakao/logout` | access Bearer 우선(없을 때 access cookie), refresh cookie |

환경 입력:

- `KAKAO_API_KEY`, `KAKAO_REDIRECT_URI`
- `ACCESS_SECRET_KEY`, `REFRESH_SECRET_KEY`
- `ACCESS_TOKEN_EXPIRE_MINUTES` (기본값 60, 단위: 분) — access token 만료 시간 조절
- `REFRESH_TOKEN_EXPIRE_DAYS` (기본값 14, 단위: 일) — refresh token 만료 시간 조절
- PostgreSQL 연결
- Valkey 연결

내부 JWT payload는 `provider`, `provider_id`, `exp`, `type`을 가진다. 현재 decode는 서로 다른 secret으로 access와 refresh를 구분하고 `type` 필드 자체는 검사하지 않는다.

## 3. 출력

| 처리 | 출력·상태 변화 |
|---|---|
| 인가 URL | Kakao authorize URL |
| 웹 callback | `LoginResponse`, access·refresh cookie |
| 모바일 로그인 | `LoginResponse` body |
| access 확인 | `AuthResponse.status` |
| refresh 확인 | 새 access cookie와 body의 `AuthResponse.access_token` |
| logout | Valkey refresh key 삭제, 두 cookie 삭제 |

저장 결과:

- PostgreSQL `users`: 최초 로그인 사용자 저장
- Valkey `refresh_token:{provider}:{provider_id}`: refresh JWT, TTL은 `REFRESH_TOKEN_EXPIRE_DAYS × 86,400`초 (기본 1,209,600초 = 14일)
- access JWT 만료: `ACCESS_TOKEN_EXPIRE_MINUTES`분 (기본값 60분)
- refresh JWT 만료: `REFRESH_TOKEN_EXPIRE_DAYS`일 (기본값 14일)

웹·모바일 `LoginResponse` body에는 현재 access·refresh token이 모두 포함된다.

## 4. 실행 진입점

```text
login_router
→ KakaoLoginService
→ Kakao token/user API
→ AuthService JWT 생성
→ UserService
→ PostgreSQL User + Valkey refresh token
```

```text
auth_router
→ AuthService JWT 검증
→ refresh이면 Valkey 저장값 비교
→ 새 access JWT
```

현재 cookie 계약:

| 설정 위치 | cookie | HttpOnly | Secure | SameSite | Max-Age |
|---|---|---:|---:|---|---:|
| 웹 callback | access | true | false | lax | 3,600초 |
| 웹 callback | refresh | false | false | lax | 1,209,600초 |
| refresh endpoint | access | false | false | lax | 3,600초 |

모바일 로그인은 cookie를 설정하지 않고 token을 body로만 반환한다.
access·refresh 확인 endpoint는 cookie가 아니라 선택적 Bearer header를 입력으로 받는다. refresh 성공 시 RN 호출자를 위해 새 access token을 응답 body에도 포함한다.

보호 API의 access token 선택 규칙은 다음과 같다.

1. `Authorization` header가 있으면 `Bearer {ROUDI access token}`만 사용한다.
2. header가 아예 없을 때만 기존 `access_token` cookie를 사용한다.
3. Bearer와 cookie가 함께 있으면 Bearer가 우선한다.
4. 잘못된 scheme·빈 토큰·공백이 섞인 Bearer는 HTTP 401 `invalid_token`이며 cookie로 되돌아가지 않는다.
5. 형식은 맞지만 손상되거나 만료된 Bearer도 cookie로 되돌아가지 않고 해당 Bearer의 인증 결과를 사용한다.

이 공통 규칙은 `/api/walk/route`, `/api/prewalk/*`, `/api/user/*`, logout에 적용한다. `/api/auth/check/access_token`은 access Bearer만, `/api/auth/check/refresh_token`은 refresh Bearer만 받는다. 두 JWT는 서로 다른 secret으로 검증되므로 서로 대체할 수 없다.

## 5. 의존하는 영역

- 사용자: 기존 사용자 조회·신규 사용자 저장
- PostgreSQL: `users`
- Valkey: refresh token 단일 활성값
- Kakao OAuth: code 교환과 사용자 정보 조회
- 설정: Kakao key·redirect URI·JWT secret
- FastAPI dependency 조립: `get_auth_service`, `get_kakao_login_service`

## 6. 결과를 전달하는 영역

- 사용자·설문 API가 access JWT의 `provider`, `provider_id`를 사용한다.
- 직접 경로 API가 인증 결과로 사용자를 찾고 RouteHistory를 저장한다.
- 챗봇 init·intent가 인증 결과로 State 소유자를 확인한다.
- logout과 refresh가 Valkey refresh token 상태를 공유한다.

## 7. 변경 시 영향 범위

| 변경 | 함께 확인할 대상 |
|---|---|
| JWT payload·secret·algorithm | 모든 `check_access_token` 호출자, 기존 token |
| `ACCESS_TOKEN_EXPIRE_MINUTES` 변경 | cookie Max-Age(3,600초 하드코딩)와 불일치 발생 가능 — cookie 설정도 함께 수정 필요 |
| `REFRESH_TOKEN_EXPIRE_DAYS` 변경 | Valkey TTL, cookie Max-Age(1,209,600초 하드코딩)와 불일치 발생 가능 — cookie 설정도 함께 수정 필요 |
| access·refresh 만료 | cookie Max-Age, Valkey TTL, 복구 안내 |
| `AuthService` 반환 tuple | user·survey·route·prewalk service와 테스트 mock |
| token 전달 위치 | 보호 API access Bearer 우선·cookie fallback, auth 확인 Bearer, 로그인 body, 웹 callback·refresh cookie |
| `LoginResponse` token 필드 | 웹·모바일 호출자와 응답 schema |
| Valkey key | 로그인·refresh·logout, 기존 로그인 세션 |
| Kakao 사용자 schema | 신규 사용자 저장과 nickname fallback |
| Provider 추가 | User entity enum, JWT, key, 사용자 조회 |

## 8. 실패·복구 방법

| 실패 | 현재 결과 | 복구 |
|---|---|---|
| access Bearer 없음·만료 | `access_expired_token` | refresh 또는 재로그인 |
| access 서명·형식 오류 | `invalid_token` | token 폐기 후 재로그인 |
| refresh Bearer 없음·만료 | `refresh_expired_token` | 재로그인 |
| refresh와 Valkey 불일치 | `invalid_token` | 재로그인 |
| Kakao code 교환 실패 | HTTP 500 `서버 내부 오류가 발생했습니다.` | 새 code로 callback 재시작 |
| Kakao 사용자 정보 실패 | HTTP 500 `서버 내부 오류가 발생했습니다.` | Kakao token·동의 항목 확인 |
| PostgreSQL 저장 실패 | 로그인 실패 | DB 복구 후 로그인 재시작 |
| Valkey 저장·조회 실패 | 로그인·refresh·logout 실패 | Valkey 복구 후 로그인 재시작 |

logout은 token으로 사용자를 식별하지 못해도 cookie를 삭제하고 `success`를 반환한다. logout 후 기존 refresh token은 Valkey 일치 검증을 통과하지 못한다.

## 9. 검증 방법

실행 순서와 실제 외부 연동 상태는 [Kakao 인증 Workflow](../architecture/workflows/kakao_authentication.md)에서 관리한다.

최소 확인 항목:

1. 인가 URL의 host·client ID·redirect URI
2. access Bearer 정상·누락·만료·손상 상태
3. refresh Bearer JWT와 Valkey 값의 일치·불일치
4. refresh 후 body access token과 access cookie 속성
5. Valkey TTL과 재로그인 시 token 교체
6. logout의 key·cookie 삭제와 refresh 재사용 실패
7. 신규·기존 사용자의 PostgreSQL 행 변화
8. 실제 Kakao callback·모바일 token 흐름

2026-09-20 로컬 격리 테스트에서 `Provider + provider_id` payload, 3개 반환 tuple, 비동기 refresh·Valkey mock, access/refresh 상호 대체 차단, Bearer/cookie 우선순위, 누락·만료·손상·동시 입력을 확인했다. 실제 Kakao·Valkey·PostgreSQL은 호출하지 않았다.

## 10. 프론트 연동 계약과 Swagger 확인

권장 호출 순서:

```text
Kakao SDK access token
→ POST /api/login/kakao/mobile-login
→ ROUDI access_token + refresh_token 보관
→ POST /api/user/survey (선택)
→ POST /api/prewalk/init
→ POST /api/prewalk/intent 반복
→ state.route_result 사용

access 만료
→ GET /api/auth/check/refresh_token (refresh Bearer)
→ body의 새 access_token으로 교체
```

직접 경로 화면은 챗봇 대신 `POST /api/walk/route`를 호출한다. 모바일 로그인 body의 `access_token`은 **Kakao SDK token**이고, 로그인 응답의 `access_token`·`refresh_token`은 **ROUDI JWT**다.

프론트의 HTTP 처리 기준:

| HTTP/응답 | 의미 |
|---|---|
| 200 + `status=success` | 성공 |
| 200 + `access_expired_token`/`invalid_token` | 서비스가 판정한 인증 상태. refresh 또는 재로그인 |
| 200 + `no_path` 등 경로 상태 | 정상 처리된 업무 결과. 서버 500으로 바꾸지 않음 |
| 400 | 서울 Polygon·수계·고속도로 등 좌표 정책 오류 |
| 401 `invalid_token` | 보호 API의 Authorization header 형식 오류. cookie fallback 없음 |
| 422 | schema·좌표·거리·공백 입력 오류. `detail[]`은 `type`, `loc`, `msg`만 포함하고 입력 원문은 반사하지 않음 |
| 500 | 예기치 않은 오류. body는 `{"detail":"서버 내부 오류가 발생했습니다."}`로 고정 |

주요 입력 제약과 예시는 `/docs`의 실제 OpenAPI schema에 반영했다.

- 직접 경로 `target_km`: 유한한 숫자 또는 숫자 문자열, `0 < target_km <= 10`; boolean·NaN·Infinity·float 변환 범위를 넘는 값은 422
- 챗봇 거리: 유한하고 0보다 커야 하며 직접 경로의 10km 상한은 적용하지 않음
- 좌표: 유한한 숫자, 서울 bounding box와 요청 처리 단계의 Polygon·도로·수계 정책 적용
- `/api/prewalk/intent`: `thread_id`, 공백이 아닌 `user_prompt`, 매 턴의 `lat`·`lon` 필수
- 설문: `안전`/`안전한 길`, `편안`/`편안한 길` 별칭과 `slow`/`normal`/`fast` 거리 값 지원

2026-09-20, 기준 commit `d2eba6d` 이후의 미커밋 worktree를 Windows 로컬 `.venv`에서 `app.openapi()`와 `tests/integration/test_api.py::TestOpenAPIContract`로 확인했다. OpenAPI에는 `AccessTokenBearer`와 `RefreshTokenBearer`가 별도 security scheme으로 생성되며, 보호 API에는 access Bearer와 호환 cookie가 함께 표시된다. 이 확인은 TestClient와 mock을 사용해 DB 초기화·Graph 로드·Kakao·OpenAI·Valkey 호출 없이 수행했다.

현재 제한·정책 주의점:

- 웹 callback과 refresh가 설정하는 cookie의 `Secure=false`는 로컬 개발 설정이다. HTTPS 배포 전 보안 설정 확정이 필요하다.
- Swagger는 Bearer와 cookie 입력을 함께 보여주지만 “header가 있으면 Bearer 우선, 잘못된 Bearer도 cookie fallback 없음”이라는 우선순위 자체는 표현하지 못하므로 이 문서를 기준으로 한다.
- JWT `type` claim은 발급하지만 decode가 claim을 직접 검사하지 않는다. 현재 access·refresh 분리는 서로 다른 secret에 의존한다.
- 실제 Kakao callback·모바일 SDK token, 실제 Valkey 단일 refresh 값·TTL, 배포 cookie/CORS, 실기기 전체 흐름은 이번 격리 검증 범위 밖이다.

## 11. 완료 기준

- 웹·모바일·refresh·logout의 입력과 출력 차이를 구분한다.
- JWT 만료, cookie Max-Age와 Valkey TTL을 추적할 수 있다.
- PostgreSQL 사용자와 Valkey refresh token의 소유 책임이 드러난다.
- token 상태별 실패 결과와 재로그인 복구 시작점을 확인할 수 있다.
- 인증 반환 계약을 사용하는 사용자·경로·챗봇 영향 범위가 연결된다.
- 현재 코드에 맞는 자동 테스트와 실제 Kakao 통합 확인 여부를 구분한다.
