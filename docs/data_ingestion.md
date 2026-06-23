# 데이터 적재 가이드

## 목적

다운로드 폴더에 받은 공공데이터 원본을 프로젝트가 읽는 위치인 `src/data/raw`로 옮긴 뒤, 기존 raw 적재기와 도메인 collector를 순서대로 실행합니다.

원본 CSV/XLSX 파일은 `.gitignore`에 의해 커밋되지 않습니다. 각 개발자는 같은 파일명을 유지한 채 로컬에서 준비해야 합니다.

## 1. 원본 파일 준비

다운로드 폴더에 아래 파일이 있는지 확인합니다.

- `전국어린이보호구역표준데이터.csv`
- `전국스마트가로등표준데이터.csv`
- `전국자전거도로표준데이터.csv`
- `서울시CCTV정보.xlsx`
- `서울시 주요 공원현황.csv` 또는 `서울시_주요_공원현황.csv`
- `서울시 자치구별 도보 네트워크 공간정보.csv` 또는 `서울시_자치구별_도보_네트워크_공간정보.csv`

파일을 `src/data/raw`로 복사합니다.

```bash
poetry run python scripts/stage_raw_data.py
```

이미 복사된 파일을 최신 다운로드 파일로 덮어쓰려면 다음처럼 실행합니다.

```bash
poetry run python scripts/stage_raw_data.py --overwrite
```

## 2. DB 테이블 생성

```bash
poetry run python -m src.main
```

## 3. Raw 데이터 적재

```bash
poetry run python -m src.data.source_collector
```

이 단계에서 `OSMSource`, `KakaoSource`, `PublicSource`, `CSVSource`가 raw 테이블을 채웁니다. 다운로드한 CSV/XLSX 파일은 `CSVSource`가 읽습니다.

## 4. 서비스용 도메인 데이터 적재

```bash
poetry run python -m src.data.data_collector
```

이 단계에서 raw 데이터를 기반으로 안전, 어린이 시설, 랜드마크, 자연, 도보 네트워크 등 서비스에서 직접 쓰는 레이어와 네트워크 데이터를 구성합니다.

## AI 응답 제한 방향

AI가 없는 정보를 만들지 않게 하려면 프롬프트만으로 막기보다 아래 흐름을 지키는 것이 좋습니다.

- DB/route engine/tool 결과를 먼저 계산합니다.
- LLM에는 계산 결과와 사용자 조건만 전달합니다.
- 프롬프트에는 제공된 데이터 밖의 장소, 수치, 시설 정보를 추측하지 말라고 명시합니다.
- 결과 객체에 없는 값은 "확인된 정보 없음"처럼 표현하도록 합니다.

즉, AI는 경로와 데이터를 결정하는 주체가 아니라, 이미 검증된 결과를 사용자에게 자연어로 설명하는 역할에 가깝게 두는 것이 안전합니다.

## 신규 데이터 확장

새 데이터가 계속 추가되는 경우에는 단순히 raw에 적재하는 것만으로 끝내지 않습니다. layer, score, profile, scoring engine 반영 기준까지 함께 확인해야 합니다.

자세한 작업 범위와 PR 분할 계획은 `docs/data_pipeline_expansion_plan.md`를 참고합니다.
