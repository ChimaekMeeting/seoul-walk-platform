# 백엔드 실행 환경

> 상태: Current  
> 기준일: 2026-07-26  
> 관련 코드: `pyproject.toml`, `docker-compose.yml`, `.env.example`, `src/main.py`

개인별 IDE·PATH 설정이 아니라 ROUDI 백엔드를 실행하기 위해 팀이 공통으로 맞춰야 하는 환경과 진입점을 정의합니다.

## 1. 지원 기준

| 항목 | 기준 |
|---|---|
| Python | 3.11 이상 |
| 패키지·가상환경 | Poetry |
| API | FastAPI·Uvicorn, `127.0.0.1:8000` |
| DB | PostgreSQL/PostGIS, `127.0.0.1:5434` |
| 캐시 | Valkey 호환 Redis, `127.0.0.1:6379` |
| 컨테이너 | Docker Compose v2 |

OS별 설치 방법은 달라도 위 버전·명령·포트·환경변수 계약을 만족해야 합니다.

## 2. 환경변수

`.env.example`을 기준으로 저장소 루트에 `.env`를 준비합니다. 실제 secret 값은 문서·로그·커밋에 기록하지 않습니다.

| 그룹 | 변수 |
|---|---|
| PostgreSQL | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_HOST`, `POSTGRES_PORT` |
| Valkey | `VALKEY_URI` |
| 인증 | `ACCESS_SECRET_KEY`, `REFRESH_SECRET_KEY`, `KAKAO_API_KEY`, `KAKAO_REDIRECT_URI` |
| 외부 데이터 | `PUBLIC_DATA_API_KEY`, `TAAS_OPEN_API_KEY` |
| AI·추적 | `OPENAI_API_KEY`, `LANGCHAIN_*` |

startup에는 PostgreSQL 연결이 필요합니다. Valkey와 외부 API는 관련 요청 workflow에서 필요합니다.

## 3. 표준 실행

```text
poetry install
docker compose up -d
poetry run python -m src.main
```

코드 진입점은 `src.main:app`, 기본 API 포트는 8000입니다. 루트 `README.md`의 Streamlit `app.py` 안내는 현재 백엔드와 일치하지 않습니다.

## 4. 실행 전 점검

```text
poetry --version
poetry run python --version
docker compose config --services
docker compose ps
```

정상 기준:

- Poetry가 Python 3.11 이상을 사용합니다.
- Compose에 `db`, `valkey`가 표시되고 5434·6379 포트가 연결됩니다.
- 서버 시작 후 `/`와 `/api/health`가 HTTP 200을 반환합니다.

`/api/health`는 PostgreSQL만 검사하며 Valkey, Graph와 외부 API는 포함하지 않습니다.

## 5. 문제 해결

| 증상 | 확인·복구 |
|---|---|
| `poetry`를 찾지 못함 | Poetry 설치와 PATH 확인 |
| `.venv`의 Python 경로가 깨짐 | Poetry 환경을 재생성하고 `poetry install` 재실행 |
| PostgreSQL 연결 거부 | `docker compose up -d db` 후 `docker compose ps` 확인 |
| Valkey 6379 충돌 | 기존 Redis·Valkey의 용도 확인 후 중복 실행 방지 |
| FastAPI 8000 충돌 | 기존 서버 종료 또는 검증 서버 포트 변경 |

기존 데이터를 보존하려면 `docker compose down -v`를 실행하지 않습니다. `init_db()`는 Entity에 없는 DB 컬럼을 삭제할 수 있으므로 기존 DB에서는 backup과 schema diff가 필요합니다. 상세 흐름은 [서버 시작 Workflow](../architecture/workflows/server_startup.md)를 따릅니다.

## 6. 현재 검증 상태

2026-07-26 Windows 환경:

| 항목 | 결과 |
|---|---|
| `.env` | 존재 확인, 값 미출력 |
| Compose | `db`, `valkey` 확인 |
| 격리 PostgreSQL | 연결 확인 |
| 기존 `.venv` | Python 3.12.2로 startup 확인 |
| FastAPI·API | startup, `/`, `/api/health` 확인 |
| Poetry CLI | 현재 셸 PATH에 없어 미검증 |

Poetry 기반 설치와 표준 실행 명령은 Poetry가 준비된 팀 환경에서 추가 검증해야 합니다.
