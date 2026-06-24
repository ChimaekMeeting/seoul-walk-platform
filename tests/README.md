# Tests

담당 QA: 예원  
최초 작성일: 2025-06

---

## 폴더 구조

```
tests/
  conftest.py              # pytest 전역 설정 (mock, 환경변수)
  unit/                    # 단위 테스트 (125개)
    test_auth_service.py
    test_banner_service.py
    test_graph_filter.py
    test_path_utils.py
    test_route_service.py
    test_scoring_engine.py
  integration/             # 통합 테스트 (23개)
    test_api.py
```

---

## 실행 방법

프로젝트 루트(`seoul-walk-platform/`)에서 실행해요.

```bash
# 단위 테스트 전체
pytest tests/unit/ -v

# 통합 테스트 전체
pytest tests/integration/ -v

# 전체 실행
pytest tests/ -v

# 특정 파일만
pytest tests/unit/test_auth_service.py -v

# 테스트 이름 키워드로 필터
pytest tests/unit/ -v -k "만료"
```

---

## 테스트 현황 (총 148개 · 전부 통과)

| 파일 | 분류 | 테스트 수 | 상태 |
|---|---|---|---|
| `test_auth_service.py` | 단위 | 21개 | ✅ |
| `test_banner_service.py` | 단위 | 22개 | ✅ |
| `test_graph_filter.py` | 단위 | 16개 | ✅ |
| `test_path_utils.py` | 단위 | 25개 | ✅ |
| `test_route_service.py` | 단위 | 16개 | ✅ |
| `test_scoring_engine.py` | 단위 | 16개 | ✅ |
| `test_api.py` | 통합 | 23개 | ✅ |

---

## 단위 테스트 상세

### `test_auth_service.py` — AuthService (21개)

JWT 토큰 발급, 검증, 만료, 상태 반환 로직을 검증해요.

| 클래스 | 검증 내용 |
|---|---|
| `TestGetAccessToken` | access token 발급, payload 구조, 만료시간 60분 |
| `TestGetRefreshToken` | refresh token 발급, payload 구조, 만료시간 14일 |
| `TestDecode` | 정상 디코딩, 만료 토큰, 잘못된 서명, None 입력 |
| `TestCheckAccessToken` | SUCCESS / INVALID_TOKEN / ACCESS_EXPIRED_TOKEN 상태 |
| `TestCheckRefreshToken` | SUCCESS / INVALID_TOKEN / REFRESH_EXPIRED_TOKEN 상태 |

### `test_banner_service.py` — BannerService (22개)

날씨·시간·이벤트 조건에 따른 배너 선택 로직을 검증해요.

| 클래스 | 검증 내용 |
|---|---|
| `TestIsHot` | 기온 파싱 (23도 기준), 소수점·음수·숫자없음 처리 |
| `TestIsHumid` | 흐림/구름/습/비 키워드 감지 |
| `TestGetBannerListPriority` | 이벤트 > 시즌 > 고정 우선순위 |
| `TestGetBannerListByHour` | 시간대별 배너 구성 (오전/저녁/야간) |
| `TestGetEventText` | D-0 / D-3 이내 / D-14 이내 텍스트 분기 |

### `test_graph_filter.py` — GraphFilter (16개)

요청 조건에 따라 그래프에서 노드를 필터링하는 로직을 검증해요.

| 클래스 | 검증 내용 |
|---|---|
| `TestExcludeUnderground` | 지하 노드 및 연결 엣지 제거 |
| `TestExcludeOverpass` | 고가 노드 및 연결 엣지 제거 |
| `TestExcludeBoth` | 두 옵션 동시 적용 |
| `TestNoFilter` | 기본값(False)에서 아무것도 제거되지 않음 |
| `TestOriginalGraphProtection` | 원본 그래프 불변 (copy 보호) |
| `TestEdgeCases` | 빈 그래프, 속성 없는 노드, 전체 제거 케이스 |

### `test_path_utils.py` — PathUtils (25개)

경로 생성의 핵심 유틸리티 함수들을 검증해요.

| 클래스 | 검증 내용 |
|---|---|
| `TestFindNearestNode` | 가장 가까운 노드 탐색, 좌표 없는 노드 스킵, 빈 그래프 |
| `TestExtractCoordinates` | 노드 ID → 좌표 변환, 없는 노드 스킵, lat/lon 순서 |
| `TestCalcDistance` | 총 이동 거리 합산, length 속성 없는 엣지 처리 |
| `TestRemoveDeadEnds` | degree=1 노드 반복 제거, 원본 그래프 보호, 사이클 그래프 |
| `TestPruneDeadEnds` | 왕복 가지 제거, max_branch_length 경계값 |

### `test_route_service.py` — RouteService

기본 3개 모드에서 status 기반 응답과 엔진 선택이 올바른지 검증해요.

| 클래스 | 검증 내용 |
|---|---|
| `TestAuthFailure` | 인증 실패 시 access/invalid token status 반환 |
| `TestUnknownMode` | 알 수 없는 모드 → ValidationError 발생 확인 |
| `TestOnewayWithoutDestination` | 편도 모드에 destination 없으면 invalid_destination 반환 |
| `TestModeRouting` | circular_random / oneway_shortest / oneway_random 엔진 호출 및 결과 전달 |

### `test_scoring_engine.py` — ScoringEngine (16개)

경로 엣지의 `custom_score` 계산 공식을 검증해요.

| 클래스 | 검증 내용 |
|---|---|
| `TestMinimumScore` | general/running 모드 모두 점수 ≥ 1.0 (Dijkstra 음수 방지) |
| `TestBlockedTags` | blocked_tags 포함 엣지는 inf 처리 |
| `TestClamping` | slope/safety 이상값(범위 초과)이 공식을 역행하지 않음 |
| `TestWeightEffect` | 가중치 변화에 따른 점수 방향 검증 |
| `TestMultiEdgeGraph` | 멀티 엣지 환경, 원본 그래프 in-place 수정 확인 |

---

## 통합 테스트 상세

### `test_api.py` — API 엔드포인트 (23개)

FastAPI `TestClient` 기반으로 HTTP 레이어(상태코드, 응답 구조)를 검증해요.  
DB/외부 API 없이 실행되도록 각 서비스를 `patch`로 교체해서 사용해요.

| 클래스 | 엔드포인트 | 테스트 수 | 검증 내용 |
|---|---|---|---|
| `TestWalkRouteAPI` | `POST /api/walk/route` | 5개 | 순환/편도 성공, FAILED 반환, 422, 500 |
| `TestAuthCheckAccessToken` | `GET /api/auth/check/access_token` | 4개 | SUCCESS, 만료, 잘못된 서명, 쿠키 없음 |
| `TestAuthCheckRefreshToken` | `GET /api/auth/check/refresh_token` | 2개 | 새 access_token 쿠키 설정, 만료 |
| `TestPrewalkInitAPI` | `POST /api/prewalk/init` | 2개 | 초기 메시지 성공, 422 |
| `TestPrewalkIntentAPI` | `POST /api/prewalk/intent` | 2개 | 대화 성공, 422 |
| `TestMapFacilitiesAPI` | `GET /api/map/facilities` | 3개 | 시설 목록 성공, 422, 500 |
| `TestMapPointsAPI` | `GET /api/map/points` | 2개 | 포인트 조회 성공, 400(잘못된 테이블) |
| `TestMapEdgesAPI` | `GET /api/map/edges` | 3개 | 엣지 조회 성공, 빈 결과, 422 |

---

## conftest.py 구조

단위 테스트는 DB, Redis, 외부 API 없이 실행되어야 해요.  
`conftest.py`가 pytest 시작 전에 아래 세 가지를 처리해요.

**1. 외부 패키지 mock**  
설치되지 않은 패키지(`redis`, `h3`, `langchain_core`, `langgraph` 등)를  
`types.ModuleType`으로 가짜 등록해 `ModuleNotFoundError`를 방지해요.

**2. src 모듈 mock**  
import 시점에 실제 연결을 시도하는 모듈들(`postgresql.py`, `valkey.py`, `agent/nodes` 등)을  
`MagicMock()`으로 선점해 DB/캐시 연결 없이 테스트가 실행되도록 해요.

**3. 환경변수 주입**  
모든 테스트에 `autouse=True`로 테스트용 시크릿 키와 DB URL을 자동 주입해요.

---

## 발견된 이슈

테스트 작성 중 확인된 코드 버그 및 개선 사항이에요.  

| 번호 | 심각도 | 위치 | 내용 | 템플릿 |
|---|---|---|---|---|
| #1 | 🔴 버그 | `RouteService.get_route()` | 알 수 없는 모드 전달 시 FAILED 대신 ValidationError 발생. LANDMARK/FLAT 모드도 동일 | 🐞 BUGFIX |
| #2 | 🟡 문서 | `AuthService.decode()` | refresh/access 동시 전달 시 refresh 우선 처리되지만 docstring에 미명시 | 📃 DOCS |
| #3 | 🟡 개선 | `RouteService.get_route()` | 미등록 모드 진입 시 로그 없어 운영 디버깅 어려움 | 🔁 REFACTOR |
| #4 | 🟡 개선 | `ScoringEngine` | `length=0` 엣지 자동 보정되지만 경고 로그 없어 데이터 이상 감지 불가 | 🔁 REFACTOR |
| #5 | 🟠 보안 | `.env` / `AuthService` | JWT 시크릿 키 32바이트 미만 경고. 운영 키 길이 확인 필요 | ⚙️ SETTING |
