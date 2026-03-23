# 🚶‍♂️ 서울시 산책경로 추천 + 움직임 유도 플랫폼 (Seoul Walk Platform)

사용자의 자연어 입력을 바탕으로 날씨, 대기질, 그리고 다양한 지리적/환경적 요소를 고려하여 **최적의 맞춤형 산책 경로를 추천해 주는 서비스**입니다. 

---

## 🚀 로컬 개발 환경 세팅 (Getting Started)

### 0. 사전 준비 (Prerequisites)
* **Python 3.11 이상**
* **Docker Desktop** (PostgreSQL 실행용)
* **Poetry** (의존성 관리자: `pip install poetry`)

### 1. 레포지토리 클론 및 환경변수 설정
```bash
# 레포지토리 클론 및 폴더 진입
git clone [레포지토리 주소]
cd seoul-walk-platform

# 환경변수 파일 복사 및 세팅
cp .env.example .env
```
> ⚠️ **주의:** `.env` 파일을 열고 각자 발급받은 `MAPBOX_API_KEY`, `OPENAI_API_KEY` 등을 채워 넣어주세요. DB 비밀번호는 기본값이 세팅되어 있으니 그대로 두셔도 무방합니다.

### 2. 데이터베이스 실행 (Docker)
```bash
# 백그라운드에서 PostgreSQL 컨테이너 실행
docker compose up -d
```

### 3. 패키지 설치 및 서버 실행
```bash
# Poetry를 통한 필수 라이브러리 설치
poetry install

# Streamlit 앱 실행
poetry run streamlit run app.py
```
> 실행 후 브라우저에서 `http://localhost:8501`로 접속하여 확인할 수 있습니다.

---

## 🌿 깃/브랜치 전략 (Git Strategy)

우리 팀은 안정적인 협업을 위해 간소화된 Git Flow를 사용합니다.

* `main` : 최종 배포용 브랜치 (건드리지 않음)
* `dev` : **기본 작업 브랜치** (모든 PR은 이곳을 향합니다)
* `feature/이름-작업명` : 개인별 기능 개발 브랜치

### 작업 순서 (Workflow)
1. `git checkout dev` (dev 브랜치로 이동)
2. `git pull origin dev` (최신 코드 받기)
3. `git checkout -b feature/yewon-map` (내 작업 브랜치 생성)
4. 작업 완료 후 `git add .` & `git commit -m "[Feat] 지도 레이어 추가"`
5. `git push origin feature/yewon-map`
6. 깃허브에서 **dev 브랜치로 PR(Pull Request)** 생성 및 팀원 리뷰 후 Merge!

### 📝 커밋 컨벤션 (Commit Convention)
* `[Feat]` : 새로운 기능 추가
* `[Fix]` : 버그 수정
* `[Docs]` : 문서 작성 및 수정 (README 등)
* `[Refactor]` : 코드 리팩토링 (기능 변화 없음)
* `[Test]` : 테스트 코드 작성
* `[Chore]` : 빌드 설정, 패키지 추가 등