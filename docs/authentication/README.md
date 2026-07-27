# 인증·Kakao 로그인 계약

> 상태: Current  
> 기준일: 2026-07-27  
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
| `GET /api/auth/check/access_token` | `access_token` cookie |
| `GET /api/auth/check/refresh_token` | `refresh_token` cookie |
| `POST /api/login/kakao/logout` | access·refresh cookie |

환경 입력:

- `KAKAO_API_KEY`, `KAKAO_REDIRECT_URI`
- `ACCESS_SECRET_KEY`, `REFRESH_SECRET_KEY`
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
| refresh 확인 | 새 access cookie와 `AuthResponse.status` |
| logout | Valkey refresh key 삭제, 두 cookie 삭제 |

저장 결과:

- PostgreSQL `users`: 최초 로그인 사용자 저장
- Valkey `refresh_token:{provider}:{provider_id}`: refresh JWT, TTL 1,209,600초
- access JWT 만료: 60분
- refresh JWT 만료: 14일

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
| access·refresh 만료 | cookie Max-Age, Valkey TTL, 복구 안내 |
| `AuthService` 반환 tuple | user·survey·route·prewalk service와 테스트 mock |
| cookie 속성 | 웹 callback, refresh, logout, 웹 호출자 |
| `LoginResponse` token 필드 | 웹·모바일 호출자와 응답 schema |
| Valkey key | 로그인·refresh·logout, 기존 로그인 세션 |
| Kakao 사용자 schema | 신규 사용자 저장과 nickname fallback |
| Provider 추가 | User entity enum, JWT, key, 사용자 조회 |

## 8. 실패·복구 방법

| 실패 | 현재 결과 | 복구 |
|---|---|---|
| access 없음·만료 | `access_expired_token` | refresh 또는 재로그인 |
| access 서명·형식 오류 | `invalid_token` | token 폐기 후 재로그인 |
| refresh 없음·만료 | `refresh_expired_token` | 재로그인 |
| refresh와 Valkey 불일치 | `invalid_token` | 재로그인 |
| Kakao code 교환 실패 | `ValueError`가 Router 밖으로 전파 | 새 code로 callback 재시작 |
| Kakao 사용자 정보 실패 | `ValueError`가 Router 밖으로 전파 | Kakao token·동의 항목 확인 |
| PostgreSQL 저장 실패 | 로그인 실패 | DB 복구 후 로그인 재시작 |
| Valkey 저장·조회 실패 | 로그인·refresh·logout 실패 | Valkey 복구 후 로그인 재시작 |

logout은 token으로 사용자를 식별하지 못해도 cookie를 삭제하고 `success`를 반환한다. logout 후 기존 refresh token은 Valkey 일치 검증을 통과하지 못한다.

## 9. 검증 방법

실행 순서와 2026-07-27 격리 검증 결과는 [Kakao 인증 Workflow](../architecture/workflows/kakao_authentication.md)에서 관리한다.

최소 확인 항목:

1. 인가 URL의 host·client ID·redirect URI
2. access 정상·만료·손상 상태
3. refresh JWT와 Valkey 값의 일치·불일치
4. refresh 후 access cookie 속성
5. Valkey TTL과 재로그인 시 token 교체
6. logout의 key·cookie 삭제와 refresh 재사용 실패
7. 신규·기존 사용자의 PostgreSQL 행 변화
8. 실제 Kakao callback·모바일 token 흐름

현재 `tests/unit/test_auth_service.py`와 인증 API 일부 mock은 현행 `Provider`·3개 반환값·비동기 refresh 계약과 일치하지 않는다. 테스트 파일의 존재를 자동 검증 완료로 간주하지 않는다.

## 10. 완료 기준

- 웹·모바일·refresh·logout의 입력과 출력 차이를 구분한다.
- JWT 만료, cookie Max-Age와 Valkey TTL을 추적할 수 있다.
- PostgreSQL 사용자와 Valkey refresh token의 소유 책임이 드러난다.
- token 상태별 실패 결과와 재로그인 복구 시작점을 확인할 수 있다.
- 인증 반환 계약을 사용하는 사용자·경로·챗봇 영향 범위가 연결된다.
- 현재 코드에 맞는 자동 테스트와 실제 Kakao 통합 확인 여부를 구분한다.
