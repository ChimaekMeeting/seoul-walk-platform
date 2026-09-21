# Cloud Run 배포 계약

> 상태: Current  
> 기준일: 2026-09-21  
> 관련 코드: `Dockerfile.api`, `cloudbuild.yaml`, `requirements.txt`, `src/config/settings.py`, `src/database/postgresql.py`, `src/entity/base.py`, `src/repository/network/graph_artifact_repository.py`, `scripts/gen_test_token.py`, `scripts/check_graph_db_consistency.py`

## 1. 책임

이 영역은 ROUDI 백엔드 API를 Google Cloud Run에 빌드·배포하고, 프로덕션 환경에서 안전하게 실행되도록 구성을 관리한다.

담당:
- Docker 이미지 빌드 (`Dockerfile.api`)
- Artifact Registry에 이미지 push
- Cloud Run 서비스 배포 (`cloudbuild.yaml`)
- 프로덕션 전용 환경변수·시크릿 관리 (Secret Manager 연동)
- DB 연결 풀·SSL 설정 (`src/database/postgresql.py`)
- DB 스키마 자동 마이그레이션 모드 (`src/entity/base.py`)
- 배포 전후 검증 스크립트 (`scripts/`)

담당하지 않음:
- 로컬 개발 환경 실행 → [`docs/operations/backend_runtime.md`](../operations/backend_runtime.md)
- Supabase PostgreSQL 스키마 설계 → 데이터 영역
- Valkey 데이터 구조 → 인증 영역
- 인증 JWT 로직 → [`docs/authentication/README.md`](../authentication/README.md)

## 2. 입력

### Cloud Build 실행 시 substitution 변수

| 변수 | 확정값 | 설명 |
|---|---|---|
| `_AR_REGION` | `asia-northeast3` | Artifact Registry 리전 |
| `_AR_REPO` | `seoul-walk` | Artifact Registry 저장소 이름 |
| `_RUN_REGION` | `asia-northeast3` | Cloud Run 배포 리전 |
| `_SERVICE` | `seoul-walk-api` | Cloud Run 서비스 이름 |
| `_TAG` | `latest` (수동 실행 시 커밋 해시 권장) | 이미지 태그 |

### Cloud Run 비민감 환경변수 (cloudbuild.yaml에 하드코딩)

| 변수 | 값 |
|---|---|
| `POSTGRES_HOST` | `aws-1-ap-northeast-2.pooler.supabase.com` |
| `POSTGRES_PORT` | `5432` |
| `POSTGRES_USER` | `postgres.cbtqbecddiepzrzrcnou` |
| `POSTGRES_DB` | `postgres` |
| `POSTGRES_SSL_MODE` | `require` |
| `DB_POOL_SIZE` | `2` |
| `DB_MAX_OVERFLOW` | `3` |
| `WALK_GRAPH_SOURCE` | `artifact` |
| `WALK_GRAPH_DATA_VERSION` | `v3-2026-09-19` |
| `WALK_GRAPH_EXPECTED_COMMIT` | `3d1696a08696c9921e7ad4b6e1c4962687cd2651` |
| `DB_AUTO_MIGRATE` | `create` |
| `LANGCHAIN_TRACING_V2` | `false` |

### Secret Manager 시크릿 (프로덕션 실행 전 미리 생성 필요)

| 시크릿 이름 | 주입되는 환경변수 |
|---|---|
| `postgres-password` | `POSTGRES_PASSWORD` |
| `valkey-uri` | `VALKEY_URI` |
| `openai-api-key` | `OPENAI_API_KEY` |
| `kakao-api-key` | `KAKAO_API_KEY` |
| `mapbox-api-key` | `MAPBOX_API_KEY` |
| `weather-api-key` | `WEATHER_API_KEY` |
| `air-korea-api-key` | `AIR_KOREA_API_KEY` |
| `public-data-api-key` | `PUBLIC_DATA_API_KEY` |
| `access-secret-key` | `ACCESS_SECRET_KEY` |
| `refresh-secret-key` | `REFRESH_SECRET_KEY` |

### Dockerfile 입력

| 파일·경로 | 역할 |
|---|---|
| `requirements.txt` | pip 의존성 (Poetry 없이 빌드) |
| `artifacts/walk_graph_v1.pkl` | 도보 그래프 artifact. 2026-09-19 빌드본은 24,845,026 bytes, 노드 160,197 / 엣지 223,693 |
| `artifacts/walk_graph_v1.manifest.json`, `artifacts/walk_graph_v1.sha256` | pkl의 `data_version`·`source_commit`·해시. 서버가 기동 때 검증한다 |
| `src/` | 애플리케이션 소스 |

**그래프 artifact 검증 계약**: 서버는 기동 때 매니페스트의 `data_version`이 `WALK_GRAPH_DATA_VERSION`과, `source_commit`이 `WALK_GRAPH_EXPECTED_COMMIT`과 글자 그대로 같은지 확인하고 다르면 로드를 거부한다(`GraphArtifactRepository.load`). `WALK_GRAPH_EXPECTED_COMMIT`을 비우면 커밋 검사만 건너뛴다. 이 값은 artifact를 빌드한 시점의 `HEAD`이며 배포하는 코드의 커밋과 다를 수 있다. pkl을 다시 빌드하면 `cloudbuild.yaml`의 두 값도 매니페스트 값으로 같이 바꿔야 한다.

`artifacts/walk_graph_*` 파일은 `.gitignore` 대상이라 저장소에 없다. 이 파일이 있는 작업 디렉터리에서만 `gcloud builds submit`으로 배포할 수 있으며, 팀 공유는 별도 압축 파일로 한다. `.gcloudignore`가 있으면 gcloud는 `.gitignore` 대신 그 파일을 쓰므로 artifact가 업로드된다.

## 3. 출력

| 결과 | 위치 |
|---|---|
| Docker 이미지 (`sha` 태그) | `asia-northeast3-docker.pkg.dev/{PROJECT_ID}/seoul-walk/seoul-walk-api:{TAG}` |
| Docker 이미지 (`latest` 태그) | 동일 경로의 `:latest` |
| Cloud Run 서비스 (배포 완료) | `seoul-walk-api` (asia-northeast3) |

**현재 운영 중인 서비스 URL**: `https://seoul-walk-api-973252334772.asia-northeast3.run.app`

2026-08-03 최초 배포 때 확인한 항목: `/api/health`, 경로 생성 API, Kakao 로그인.
2026-09-21 재배포 결과는 [10. 완료 기준](#10-완료-기준)에 적었다.

## 4. 실행 진입점

### Cloud Build 파이프라인 (`cloudbuild.yaml`)

```text
1. build  : docker build -f Dockerfile.api → 이미지 생성
2. push-sha   : Artifact Registry에 커밋 해시 태그 push
   push-latest: Artifact Registry에 latest 태그 push  (병렬)
3. deploy : gcloud run deploy seoul-walk-api
           → 환경변수 주입 + 시크릿 마운트 + Cloud Run 서비스 갱신
```

### Dockerfile 실행 흐름 (`Dockerfile.api`)

```text
FROM python:3.12-slim (linux/amd64 고정)
→ pip install -r requirements.txt
→ COPY artifacts/ (walk graph pkl — 별도 레이어로 캐시 분리)
→ COPY src/
→ useradd appuser (1000)
→ CMD: uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1
```

**주의**: `fiona`는 `libexpat.so.1` 부재로 직접 import 불가하지만 API 런타임 경로에서 호출되지 않아 무관하다. apt 패키지 추가 없이 빌드된다.

**GUI 의존 패키지 금지**: 이 이미지는 apt 패키지를 설치하지 않으므로 `libxcb.so.1` 등 GUI 라이브러리가 없다. GPS Art가 `import cv2`를 하므로 `opencv-python`(GUI 의존)이 아니라 `opencv-python-headless`를 `requirements.txt`와 `pyproject.toml`에 선언한다. `opencv-python`으로 배포하면 `src/service/route/gps_art_service.py` import에서 `ImportError: libxcb.so.1`로 프로세스가 종료되어 Cloud Run이 "PORT에서 응답하지 않음"으로 배포를 실패 처리한다(2026-09-21 revision `seoul-walk-api-00011-t4f`에서 확인).

### 서버 시작 시 DB 마이그레이션 (`src/entity/base.py`)

`DB_AUTO_MIGRATE` 값에 따라 startup 시 스키마를 자동 동기화한다.

| 모드 | 동작 |
|---|---|
| `full` (로컬 기본값) | CREATE TABLE + ADD COLUMN + DROP COLUMN |
| `create` (프로덕션 기본값) | CREATE TABLE + ADD COLUMN만 허용, DROP 차단 |
| `off` | 스키마 변경 없음 |

프로덕션에서는 `create`를 사용한다. 컬럼을 실제로 제거해야 할 때는 `off`로 전환 후 수동 마이그레이션한다.

## 5. 의존하는 영역

| 의존 대상 | 역할 |
|---|---|
| Supabase PostgreSQL (Session Pooler) | 프로덕션 DB. `sslmode=require`, 포트 5432 |
| Valkey (Upstash 또는 동급) | refresh token 저장소. `VALKEY_URI` 시크릿으로 주입 |
| `artifacts/walk_graph_v1.pkl` | 도보 그래프. `WALK_GRAPH_SOURCE=artifact`일 때 사용 |
| Google Artifact Registry | 빌드 이미지 저장소 |
| Google Secret Manager | 민감 환경변수 런타임 주입 |
| Google Cloud Build | CI/CD 파이프라인 실행 |

**DB 풀 설계 근거 (Supabase 대시보드 확인값 기준)**:

Supabase Session Pooler에는 방향이 다른 두 가지 커넥션 한도가 있다.

| 한도 | 값 | 방향 | 의미 |
|---|---|---|---|
| Connection pool size | 15 | pooler → Postgres | pooler가 실제 Postgres에 열 수 있는 최대 커넥션 수. 이 값을 초과하면 쿼리가 대기한다. |
| Max client connections | 200 | 앱 → pooler | 앱 인스턴스들이 pooler에 동시에 붙을 수 있는 최대 소켓 수. |

우리가 `pool_size=2, max_overflow=3`으로 설정한 근거는 **pooler → Postgres 방향의 15** 한도다. Cloud Run 인스턴스 한 개가 최대 `pool_size + max_overflow = 5` 커넥션을 pooler 쪽으로 열고, `max-instances=3`이므로 최악의 경우 `3 × 5 = 15`로 pooler → Postgres 한도에 딱 맞는다. 인스턴스를 늘리거나 풀 크기를 키우면 이 한도를 초과해 쿼리 대기가 발생한다.

## 6. 결과를 전달하는 영역

- **Cloud Run 서비스** (`seoul-walk-api`): 배포 완료 후 API 트래픽을 처리한다.
- **프론트엔드·모바일 앱**: 배포된 서비스 엔드포인트를 사용한다.
- **`scripts/gen_test_token.py`**: 배포 후 로컬에서 테스트 토큰을 생성해 API를 검증한다.

## 7. 변경 시 영향 범위

| 변경 | 함께 확인할 대상 |
|---|---|
| `requirements.txt` 의존성 추가·삭제 | Docker 빌드 캐시 무효화, `pyproject.toml`과 동기화 여부 |
| `artifacts/walk_graph_v1.pkl` 교체 | `WALK_GRAPH_DATA_VERSION`, `WALK_GRAPH_EXPECTED_COMMIT` 값 갱신 필요 |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `max-instances` × (pool_size + max_overflow) ≤ 15 (pooler → Postgres 한도) 초과 여부 확인 |
| `DB_AUTO_MIGRATE` 모드 변경 | 프로덕션에서 `full`로 바꾸면 컬럼 DROP 위험 — 반드시 backup 후 실행 |
| Secret Manager 시크릿 이름 변경 | `cloudbuild.yaml`의 `--set-secrets` 값과 동기화 필요 |
| Cloud Run `--max-instances` 변경 | DB 풀 한도 재계산 필요 |
| `_AR_REGION` / `_RUN_REGION` 변경 | Artifact Registry URL, Cloud Run 배포 리전 전체 갱신 |
| `POSTGRES_SSL_MODE` 변경 | 로컬 개발 환경과 혼용 시 SSL 충돌 가능 |
| GUI 의존 패키지(`opencv-python` 등) 추가 | slim 이미지에 시스템 라이브러리가 없어 기동 실패. `-headless` 변형을 쓰거나 `Dockerfile.api`에 apt 레이어 추가 |
| `pyproject.toml` 의존성 변경 | `poetry.lock`을 저장소가 쓰는 Poetry 버전(현재 lock은 2.3.2 생성)으로 재생성하고 `requirements.txt`와 동기화 |

## 8. 실패·복구 방법

| 실패 | 원인 | 복구 |
|---|---|---|
| Docker 빌드 실패 | `requirements.txt` 의존성 충돌, `fiona` 외 apt 의존 패키지 | 의존성 버전 고정 확인, apt 레이어 추가 검토 |
| Artifact Registry push 실패 | IAM 권한 부족 | Cloud Build 서비스 계정에 `artifactregistry.writer` 역할 부여 |
| Secret Manager 시크릿 누락 | 시크릿 미생성 | `gcloud secrets create` 후 재배포 |
| Cloud Run 배포 실패 — DB 연결 거부 | `POSTGRES_SSL_MODE`, 호스트, 포트 오설정 | 환경변수 값 재확인 후 재배포 |
| DB 풀 초과 | `max-instances` × (pool_size + max_overflow) > 15 (pooler → Postgres 한도) | `max-instances` 축소 또는 풀 크기 축소 |
| 서버 시작 시 컬럼 DROP (프로덕션) | `DB_AUTO_MIGRATE=full`로 잘못 설정 | `create` 모드로 재배포, 삭제된 컬럼은 Supabase 백업에서 복구 |
| walk graph 불일치 | pkl과 DB link_id 불일치 | `scripts/check_graph_db_consistency.py`로 확인 후 artifact 재빌드 |
| 기동 중 Graph artifact 로드 거부 | `cloudbuild.yaml`의 `WALK_GRAPH_DATA_VERSION`·`WALK_GRAPH_EXPECTED_COMMIT`이 매니페스트와 다름 | 매니페스트 값으로 맞춘 뒤 재배포 |
| 배포 단계 `container failed to start` | 기동 중 import 오류·그래프 검증 실패 등으로 프로세스 종료 | 아래 "실패한 revision 로그 확인"으로 원인을 읽는다. 새 revision이 준비되지 않으면 기존 revision이 트래픽을 유지한다 |
| Cloud Run cold start 지연 | `min-instances=0` | 허용 범위 내면 정상. 개선 필요 시 `min-instances=1` 검토 |

## 9. 검증 방법

### 배포 후 기본 확인

서비스 URL: `https://seoul-walk-api-973252334772.asia-northeast3.run.app`

```bash
# 헬스체크 (PostgreSQL 연결 여부)
curl https://seoul-walk-api-973252334772.asia-northeast3.run.app/api/health

# 루트 응답
curl https://seoul-walk-api-973252334772.asia-northeast3.run.app/
```

### 기동 로그 확인

새 revision의 기동 로그로 그래프 로드·가중 탐색 상태를 확인한다. `{REVISION}`은 `gcloud run services describe seoul-walk-api --region=asia-northeast3 --format='value(status.latestReadyRevisionName)'`로 얻는다.

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="seoul-walk-api" AND resource.labels.revision_name="{REVISION}"' \
  --project=roudi-backend --order=asc --limit=80 --format='value(timestamp,severity,textPayload)'
```

정상 기동에서 다음 순서의 로그가 보인다.

```text
[init_db] 마이그레이션 모드: create
배포용 Graph artifact를 로드합니다: /app/artifacts/walk_graph_v1.pkl
ALT 휴리스틱 준비 완료: method=planar k_requested=8 k_actual=8 ...
가중 비용 준비 완료: 적재율={'safety_score': ..., 'accident_score': ..., 'slope_score': ...}, 기준=0.95
Application startup complete.
```

가중 비용 로그의 적재율이 기준(`WALK_SCORE_COVERAGE_MIN`, 기본 0.95) 미만이면 서버는 거리 전용 탐색으로 폴백한다.

### 실패한 revision 로그 확인

배포 단계가 `container failed to start`로 실패하면 deploy 단계 로그의 `Logs URL`에 있는 revision 이름으로 같은 명령을 실행한다. `cloudbuild.yaml`이 `CLOUD_LOGGING_ONLY`라 `gcloud builds submit` 터미널에는 빌드 로그가 흐르지 않는다. 빌드 단계 로그는 `resource.type="build" AND resource.labels.build_id="{BUILD_ID}"`로 조회한다.

### 테스트 토큰 생성 (인증 API 검증용)

경로 생성 API는 유효한 access token이 없으면 HTTP 200 본문의 `status`로 `access_expired_token`(토큰 없음·만료) 또는 `invalid_token`(서명 불일치)을 돌려주고 경로 엔진을 실행하지 않는다. `Authorization: Bearer` 값에 공백·줄바꿈이 있으면 HTTP 401이다. `gen_test_token.py`로 만든 토큰이 통과하려면 로컬 `.env`의 `ACCESS_SECRET_KEY`가 운영(Secret Manager `access-secret-key`)과 같아야 한다.

```bash
# .env에 ACCESS_SECRET_KEY가 있어야 함
python scripts/gen_test_token.py
python scripts/gen_test_token.py --provider-id my_id --hours 24
```

출력 예:
```
provider_id : test_9999
expires_at  : 2026-08-06 20:00 KST
token       : eyJ...
```

### walk graph ↔ DB 정합성 확인

```bash
# 1. DB link_id 목록 추출 (Supabase 또는 로컬 DB에서)
psql ... -c "COPY (SELECT link_id FROM walk_edges) TO STDOUT" > /tmp/db_link_ids.txt

# 2. 정합성 검사
python scripts/check_graph_db_consistency.py
# 기대값: ✅ 정합성 OK — 그래프의 모든 link_id가 DB에 존재
```

### Cloud Build 수동 실행 (배포 트리거 없이 테스트)

```bash
gcloud builds submit . \
  --config=cloudbuild.yaml \
  --substitutions=_TAG=$(git rev-parse --short HEAD)
```

## 10. 완료 기준

### 2026-09-21 재배포 (revision `seoul-walk-api-00012-c6m`)

환경: 운영 Cloud Run(`roudi-backend`, asia-northeast3). 재현은 9장의 "기동 로그 확인" 명령과 아래 curl로 한다. 일회성 관측값이며 고정 기대값이 아니다.

확인 완료:
- 배포 단계 성공, 해당 revision이 트래픽 100%를 받음. 첫 시도(revision `00011-t4f`)는 `opencv-python`의 `libxcb.so.1` 부재로 실패했고 `opencv-python-headless`로 바꿔 해결
- `/api/health` HTTP 200
- 기동 로그: `create` 마이그레이션 모드 실행, Graph artifact 로드(`v3-2026-09-19` 검증 통과), ALT 준비 완료, 가중 비용 준비 완료(적재율 세 점수 모두 1.0, 기준 0.95), `Application startup complete`. 서버 시작부터 준비 완료까지 약 21초
- `GET /api/map/points/safety?lat=37.5759&lon=126.9768&radius_m=1000` HTTP 200, 240건(cctv 220, streetlight 20)

확인하지 못한 항목:
- 경로 생성 API 재배포 후 응답(테스트 토큰 인증이 통과하지 않아 경로 엔진 실행까지 도달하지 못함)
- Kakao 로그인
- `check_graph_db_consistency.py`와 pkl ↔ Supabase 값 대조

알려진 제약:
- 운영은 `WALK_GRAPH_SOURCE=artifact`이므로 안전·사고·경사 점수를 pkl에서 읽는다. `GraphRepository.load_graph()`가 `walk_edges`의 점수 컬럼을 읽는 것은 `WALK_GRAPH_SOURCE=database`일 때뿐이다. 이 컬럼이 Supabase에서 비어 있어도 artifact 모드 서비스에는 영향이 없으나, `database` 모드로 바꾸면 적재율 게이트(0.95)에 걸려 가중 탐색이 꺼진다.
- `DB_AUTO_MIGRATE=create`는 없는 컬럼을 `ADD COLUMN`으로 추가할 뿐 값을 채우지 않는다.

### 2026-08-03 최초 배포

2026-08-03 기준 아래 항목 모두 확인 완료:

- `seoul-walk-api` Cloud Run 서비스 배포 완료 및 운영 중
- `/api/health` HTTP 200, PostgreSQL 연결 확인
- 경로 생성 API 동작 확인
- Kakao 로그인 동작 확인
- DB 풀 설정 `max-instances(3) × (pool_size(2) + max_overflow(3)) = 15` ≤ Supabase pooler → Postgres 한도(15) 충족
- `DB_AUTO_MIGRATE=create`로 기동 시 컬럼 DROP 없음 확인
- Secret Manager 시크릿 10개 주입 상태로 서버 기동 확인

재배포 시 추가로 확인할 항목:

- `gen_test_token.py`로 생성한 토큰으로 인증 필요 API 호출 성공
- `check_graph_db_consistency.py`로 walk graph ↔ DB link_id 정합성 확인
- 기동 로그에서 Graph artifact 로드와 가중 비용 적재율(기준 0.95 이상) 확인
- `cloudbuild.yaml`의 `WALK_GRAPH_DATA_VERSION`·`WALK_GRAPH_EXPECTED_COMMIT`이 `artifacts/walk_graph_v1.manifest.json`과 같은지 확인
