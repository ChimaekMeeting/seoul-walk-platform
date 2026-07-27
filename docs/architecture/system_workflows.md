# ROUDI 백엔드 Workflow 지도

> 상태: Current  
> 기준일: 2026-07-27  
> 관련 코드: `src/main.py`, `src/interfaces/`, `src/service/`, `src/agent/`, `src/route_engine/`, `src/data/`

이 문서는 여러 백엔드 영역을 가로지르는 주요 workflow의 목록과 연결 관계를 관리합니다. 정상·실패 분기와 실행 증거는 `workflows/`의 개별 문서에서 관리합니다.

## Workflow 목록

| Workflow | 시작점 | 최종 결과 | 주요 상태 저장소 | 검증 상태 | 상세 문서 |
|---|---|---|---|---|---|
| 서버 시작 | FastAPI lifespan | API 요청 수신 가능 | PostgreSQL, 메모리 Graph | 코드 추적 완료·빈 Graph 로컬 통합 확인 | [서버 시작](workflows/server_startup.md) |
| Kakao 인증 | `/api/login/**`, `/api/auth/**` | 사용자와 JWT | PostgreSQL, Valkey, cookie | 내부 인증 격리 통합 확인·Kakao 로그인 미확인 | [Kakao 인증](workflows/kakao_authentication.md) |
| 직접 경로 추천 | `POST /api/walk/route` | 경로 좌표와 상태 | 메모리 Graph, RouteHistory | 코드 추적 완료·3개 모드 격리 통합 확인 | [직접 경로 추천](workflows/walk_route_request.md) |
| 챗봇 경로 추천 | `POST /api/prewalk/init`, `/intent` | 대화 State와 경로 | PostgreSQL, Valkey | OpenAI/Kakao/DB/Valkey/경로 통합 확인 | [챗봇 경로 추천](workflows/prewalk_conversation.md) |
| 지도·날씨·배너 조회 | `/api/map/**`, `/api/weather`, `/api/banner` | 지도·환경·배너 응답 | PostgreSQL, 외부 응답 | DB/Kakao/마라톤 확인·공공데이터 실패 확인 | [지도·환경·배너](workflows/map_environment_banner.md) |
| V1 데이터 적재 | Data Collector | NODE·LINK·Layer와 재로딩된 Graph | PostgreSQL, 메모리 Graph | 격리 DB rebuild·실데이터 Graph 확인 | [V1 데이터 적재](workflows/v1_data_ingestion.md) |

## Workflow 사이의 연결

```text
V1 데이터 적재
→ 서버 재시작
→ PostgreSQL NODE·LINK를 메모리 Graph로 로드
→ 직접 경로 추천과 챗봇 경로 추천에서 사용

Kakao 인증
→ access token 발급
→ 사용자·직접 경로·챗봇 요청에서 사용

지도·날씨·배너 조회
→ 독립 API 응답
→ 날씨·주소 조회 일부는 챗봇 초기화에서도 사용
```

## 작성·검증 원칙

1. 코드를 먼저 확인하고 실제 호출 순서를 기록합니다.
2. 실행 전 예상 결과를 작성합니다.
3. 정상 사례와 대표 실패 사례를 실행합니다.
4. HTTP 응답뿐 아니라 로그·DB·Valkey·메모리 상태를 확인합니다.
5. mock을 사용한 경계와 실제 외부 호출을 구분합니다.
6. 실행하지 못한 항목은 추측으로 채우지 않고 미검증으로 표시합니다.
7. 기존 개발 DB에 영향을 줄 수 있는 startup·rebuild는 격리 환경에서 검증합니다.

## 개별 Workflow 공통 형식

개별 문서는 영역 계약의 10개 항목을 반복하지 않고 다음 6개 항목만 사용합니다.

```text
목적과 시작 조건
→ 참여 코드
→ 정상 흐름
→ 상태 변화와 결과
→ 실패·복구
→ 검증 결과
```

### 6개 항목을 사용하는 이유

영역 계약은 한 영역을 독립적으로 맡기기 위한 경계를 10개 항목으로 정의한다. Workflow는 그 계약들을 실제 요청 순서로 연결하고 실행 증거를 남기는 문서이므로 다음처럼 압축한다.

| 영역 계약의 내용 | Workflow에서 확인하는 위치 |
|---|---|
| 책임·입력 | 목적과 시작 조건 |
| 실행 진입점·의존 영역·전달 영역 | 참여 코드 |
| 입력에서 출력까지의 연결 | 정상 흐름 |
| 출력·저장 상태·변경 영향 | 상태 변화와 결과 |
| 실패·복구 | 실패·복구 |
| 검증·완료 기준 | 검증 결과 |

Workflow는 영역 자체를 다시 설명하지 않는다. 상세 책임과 완료 기준은 영역 계약에 링크하고, Workflow에는 영역 간 연결·상태 변화·실패 분기·실행 결과만 기록한다.

## Workflow를 사용해 작업하는 순서

```text
Workflow 목록에서 변경할 흐름 선택
→ 참여 코드와 관련 영역 계약 확인
→ 맡을 작업의 책임·입력·출력 확정
→ 코드 변경
→ 정상 사례와 대표 실패 사례 검증
→ Workflow 검증 결과와 관련 영역 계약 갱신
→ Workflow 목록의 검증 상태 갱신
```

코드만 동작하는 것으로 끝내지 않는다. 관련 영역의 완료 기준을 만족하고, Workflow의 연결 결과를 실제 응답·로그·저장소에서 확인했을 때 작업이 완료된 것으로 판단한다.

## 공통 검증 상태

| 상태 | 의미 |
|---|---|
| 코드 추적 전 | 진입점과 호출 관계를 아직 함께 확인하지 않음 |
| 코드 추적 완료 | 현재 코드의 호출·분기 확인 완료 |
| 격리 실행 확인 | fixture 또는 mock 경계로 실행 완료 |
| 로컬 통합 확인 | PostgreSQL·Valkey 등 로컬 의존성을 포함해 실행 완료 |
| 외부 통합 확인 | 실제 외부 API까지 포함해 실행 완료 |
| 미검증 | 실행 증거가 없거나 전제 조건이 준비되지 않음 |
