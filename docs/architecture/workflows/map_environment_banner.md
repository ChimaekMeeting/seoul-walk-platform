# 지도·날씨·배너 조회 Workflow

> 상태: Current  
> 기준일: 2026-07-27  
> 관련 코드: `src/interfaces/api/map_router.py`, `src/interfaces/api/weather_router.py`, `src/interfaces/api/banner_router.py`, `src/service/route/map_service.py`, `src/service/route/banner_service.py`  
> 검증 상태: 코드 추적 완료·DB/Kakao/마라톤 통합 확인·공공데이터 API 실패 확인

## 1. 목적과 시작 조건

지도 표시용 시설·Layer·도보 Edge, 현재 날씨·대기질, 상황별 배너를 조회하는 세 흐름이다. 인증은 요구하지 않는다.

| 구분 | 시작점 | 데이터 원천 |
|---|---|---|
| 지도 | `/api/map/facilities`, `/points/**`, `/edges` | Kakao Local API, PostgreSQL |
| 환경 | `/api/weather` | 기상청·에어코리아·Kakao 주소 API |
| 배너 | `/api/banner` | PostgreSQL banner, 날씨, 마라톤 사이트 |

공통 입력은 `lat`, `lon`이며 지도 반경과 배너 기준 시각을 선택적으로 받는다. 현재 router에는 서울 범위와 양수 반경 검증이 없다.

## 2. 참여 코드

| 코드 | 역할 |
|---|---|
| `map_router.py`, `map_service.py` | 시설·Layer·Edge 응답 조정 |
| `repository/layer/`, `EdgeRepository` | PostGIS 반경 조회 |
| `KakaoClient` | 시설 검색과 좌표→주소 변환 |
| `weather_router.py`, `WeatherClient` | 기상·대기질 병렬 조회 |
| `banner_router.py`, `BannerService` | 이벤트→시즌→고정 배너 조합 |
| `BannerRepository`, `MarathonClient` | 6개 seed 배너와 서울 대회 조회 |

## 3. 정상 흐름

```text
지도 시설 → Kakao 장소 검색(페이지당 3건, 최대 3페이지) → 시설 목록
지도 Layer → PostGIS ST_DWithin → Point 목록
지도 Edge → PostGIS 반경 조회 → GeoJSON LineString을 path로 변환

날씨 → 기상청 초단기실황
     ↘ Kakao 주소로 자치구 확인 → 에어코리아
→ weather_info와 air_info

배너 → 날씨 조회 + DB banner 조회 + 서울 마라톤 조회
→ 이벤트 → 더운 날 시즌 → 시간대 고정 순서로 items 구성
```

지도 Point의 category는 safety·nature·child·running Layer만 반환한다. landmark는 좌표만 반환하고, Edge path는 `[lon, lat]` 순서다.

## 4. 상태 변화와 결과

- 모든 API는 조회 전용이다.
- banner 6건은 서버 startup의 `init_db()`에서 비어 있을 때 seed된다.
- 배너의 `scoring`은 이후 경로 profile 입력으로 사용할 수 있는 가중치 묶음이다.
- 날씨와 대기질은 일부 또는 전체가 실패해도 현재 HTTP 200이며 실패한 값은 `null`이 된다.
- 배너는 날씨·마라톤 실패를 흡수하고 DB 고정 배너를 반환한다. DB 조회 실패만 `status=db_error`, 빈 items가 된다.

## 5. 실패·복구

| 실패 | 현재 결과 | 복구 |
|---|---|---|
| 지도 입력 타입 누락·오류 | HTTP 422 | query 수정 |
| Kakao 시설 또는 Point 조회 예외 | HTTP 500 | key·외부 응답·DB 확인 |
| Edge DB 예외 | repository가 빈 목록으로 축소 | DB 로그 확인 |
| Edge `link_id` 타입 불일치 | HTTP 500 응답 검증 실패 | entity/schema 계약 수정 필요 |
| 기상·대기질 파싱·HTTP 실패 | HTTP 200, 해당 값 `null` | 공공데이터 key·응답 확인 후 재요청 |
| 날씨·마라톤 배너 입력 실패 | 나머지 DB 배너 반환 | 외부 연동 복구 후 재요청 |
| banner DB 실패 | HTTP 200 / `db_error` | PostgreSQL 복구 |

현재 외부 client는 Kakao 일부 메서드와 공공데이터 응답의 HTTP 상태를 일관되게 검사하지 않는다. 장애 조사 시 HTTP 200만 보지 말고 응답 body와 서버 로그를 함께 확인한다.

## 6. 검증 결과

2026-07-27 격리 PostgreSQL과 실제 외부 API로 서울시청 부근을 조회했다.

| API | 결과 |
|---|---|
| Kakao 카페 500m | HTTP 200, 최대치 9건 |
| safety / landmark / child / running 1km | HTTP 200, 격리 DB 적재 0건과 일치 |
| nature 1km | HTTP 200, 공원 Polygon centroid 24건 |
| Edge 100m | 23건 조회 후 `link_id` 정수→문자열 검증 실패로 HTTP 500 |
| 날씨·대기질 | 외부 403, API는 HTTP 200과 `null` 두 개 반환 |
| 배너 22시 | HTTP 200 / `success`, 마라톤 이벤트 1건과 `night` 1건 |

격리 DB에는 banner 6, nature 1,888, walk edge 279,016건이 있었고 나머지 조회 Layer는 비어 있었다. 실제 Kakao 주소와 시설, 마라톤 사이트는 응답했고 공공데이터 두 API는 403이었다.

`tests/unit/test_banner_service.py`는 34개 중 23개 통과, 11개 실패했다. 실패 테스트는 과거 한글 날씨 키를 사용해 현재 영문 키 계약과 맞지 않으므로 현재 자동 완료 기준으로 사용할 수 없다.
