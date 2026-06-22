# 데이터 적재 및 score/profile 확장 작업 계획

## 목적

이 문서는 신규 데이터가 계속 추가되는 상황에서 데이터 적재, score 계산, profile 확장을 일관되게 관리하기 위한 작업 범위를 정의합니다.

채원 담당 업무는 단순히 로컬에 데이터를 적재하는 일이 아니라, 새 데이터가 들어왔을 때 아래 흐름이 깨지지 않도록 규칙과 검수 체계를 만드는 것입니다.

```text
원본 데이터
→ raw 적재
→ layer 변환
→ walk_edges.*_score 계산
→ profiles.py 가중치 반영
→ scoring_engine.py 경로 비용 계산
→ AI 응답 제한
```

## 현재 이미 있는 것

아래 항목은 새로 만들 필요 없이 기존 구조를 확장합니다.

- `csv_raw`, `osm_raw`, `public_raw`, `kakao_raw` raw 테이블 구조
- `source_collector → data_collector` 적재 실행 흐름
- `src/data/sources/`의 source 단위 수집 구조
- `src/data/collectors/`의 collector 구조
- `save() = update_node() + update_edge()` collector 작성 규칙
- Repository를 통한 DB 접근 규칙
- `docs/data_ingestion.md`의 기본 적재 실행 가이드
- `scripts/stage_raw_data.py`의 다운로드 파일 준비 흐름

## 진짜로 채워야 하는 것

### 1. 신규 데이터 추가 체크리스트

새 데이터가 들어왔을 때 아래 항목을 반드시 확인합니다.

```text
1. source_type: CSV / XLSX / API / OSM / GeoJSON 중 무엇인가?
2. 좌표가 있는가? 없으면 geocoding이 필요한가?
3. geometry는 POINT / LINESTRING / POLYGON 중 무엇인가?
4. 어느 raw 테이블에 저장되는가?
5. 어느 layer/entity로 변환되는가?
6. 어떤 walk_edges.*_score 컬럼에 영향을 주는가?
7. score 방향은 bonus / penalty / mode-specific 중 무엇인가?
8. 어느 profile에서 이 score를 사용할 수 있는가?
9. 정적 데이터인가, 실시간/주기 갱신 데이터인가?
10. AI가 사용자에게 보장해도 되는 데이터 근거가 있는가?
```

원칙:

- score가 없으면 `profiles.py`에 반영하지 않습니다.
- 실제 데이터 근거가 없으면 profile을 만들지 않습니다.
- 데이터 근거가 약한 조건은 `unsupported_preferences`로 안내합니다.
- 자동화는 후보를 제안할 수 있지만, 최종 layer/score/profile 연결은 팀이 승인한 규칙만 사용합니다.

### 2. 현재 score 의미와 동작 고정

현재 존재하는 score를 먼저 문서화해야 합니다.

| score | 현재 의미 | 현재 사용 위치 | 확인 필요 |
| --- | --- | --- | --- |
| `safety_score` | 안전 관련 점수 | default, flat, child, running, landmark | bonus로 유지 |
| `nature_score` | 자연/녹지 관련 점수 | default, flat, child, running, landmark | bonus로 유지 |
| `slope_score` | 평탄함 점수, 높을수록 평지 | flat, child, running 등 | running 모드 방향 확인 필요 |
| `running_score` | 러닝 코스 관련 점수 | running | bonus로 유지 |
| `landmark_score` | 랜드마크 접근성 점수 | landmark | bonus로 유지 |
| `child_score` | 어린이 관련 안전/시설 점수 | child | bonus로 유지 |

특히 `slope_score`는 현재 모드별로 다르게 반영됩니다.

```text
일반 모드:
  slope_score 높음 → cost 낮음 → 평탄한 길 선호

running 모드:
  slope_score 높음 → cost 높음 → 평탄한 길 회피
```

이 동작은 코드상 존재하는 실제 동작이지만, 제품 정책으로 의도된 것인지 명확히 문서화되어 있지 않습니다. 따라서 현재 단계에서는 이를 버그로 단정하지 않고 `mode-specific score effect`의 대표 사례로 기록합니다.

`slope_score` 정책 메모:

```text
- 현재 의미: 높을수록 평탄한 길
- 일반 모드 효과: bonus, 값이 높을수록 cost 감소
- running 모드 효과: penalty, 값이 높을수록 cost 증가
- 현재 분류: mode-specific
- 리팩토링 전 조치: 현재 동작을 회귀 테스트로 고정
- 정책 결정 전 제한: running 모드의 slope 반영 방식은 임의로 수정하지 않음
```

신규 score를 추가할 때는 단순히 bonus/penalty로만 분류하지 않고 아래 중 하나로 명시합니다.

```text
bonus:
  값이 높을수록 경로 비용이 낮아지는 score

penalty:
  값이 높을수록 경로 비용이 높아지는 score

mode-specific:
  mode/profile에 따라 효과가 달라지는 score
```

score effect가 불명확한 데이터는 profile에 반영하지 않습니다.

### 3. score catalog 작성

새 score를 추가하기 전에 score catalog를 먼저 정의합니다.

권장 필드:

```text
score_name
meaning
value_direction
cost_effect
mode_specific_effect
source
raw_table
layer
profiles
requires_team_confirmation
```

예시:

| score_name | meaning | value_direction | cost_effect | profiles | 확인 필요 |
| --- | --- | --- | --- | --- | --- |
| `nature_score` | 자연 친화도 | 높을수록 자연 많음 | bonus | default, scenic, running | 아니오 |
| `slope_score` | 평탄함 | 높을수록 평지 | mode-specific | flat, child, running | 예 |
| `crowd_score` | 혼잡도 | 높을수록 혼잡 | penalty | quiet, heat_safe | 예 |
| `shade_score` | 그늘/가로수 밀도 | 높을수록 그늘 많음 | bonus | shade, heat_safe | 예 |

### 4. scoring_engine 회귀 테스트

`scoring_engine.py`를 일반화하기 전에 현재 동작을 테스트로 고정합니다.

최소 테스트 항목:

```text
1. default profile에서 safety/nature/slope가 높은 edge는 cost가 낮아지는가?
2. child profile에서 child_score가 높은 edge는 cost가 낮아지는가?
3. landmark profile에서 landmark_score가 높은 edge는 cost가 낮아지는가?
4. running profile에서 running_score가 높은 edge는 cost가 낮아지는가?
5. running profile에서 slope_score가 높은 edge는 현재 cost가 높아지는가?
6. blocked_tags가 포함된 edge는 custom_score가 inf가 되는가?
```

주의:

- 이 테스트는 "현재 동작이 옳다"를 의미하지 않습니다.
- 리팩토링 전후 결과가 의도치 않게 바뀌지 않도록 현재 동작을 고정하는 목적입니다.
- `slope_score`의 running 모드 동작은 팀 확인 후 유지 또는 수정합니다.

### 5. registry.yaml 도입

팀이 승인한 데이터 규칙을 파일로 관리합니다.

초기 위치:

```text
src/data/registry.yaml
```

이 파일은 "팀이 이 데이터는 이렇게 쓰기로 승인했다"는 데이터 계약서입니다. AI나 자동 분석기가 추측한 결과를 그대로 적는 곳이 아니며, `approved: true`인 데이터만 score/profile 확장에 반영합니다.

예시:

```yaml
street_tree:
  source_type: csv
  file: 전국가로수길정보표준데이터.csv
  raw_table: csv_raw
  geometry: LINESTRING
  layer: nature_layer
  score_column: nature_score
  score_effect: bonus
  profiles:
    - default
    - running
    - scenic
  update_type: static
  approved: false
```

역할:

- 자동 추론 결과가 아니라 팀이 승인한 데이터 계약입니다.
- `approved: true`인 데이터만 실제 profile/score 확장에 반영합니다.
- 데이터가 있어도 `approved: false`이면 AI가 해당 조건을 보장하지 않습니다.

### 6. intake inspector MVP

새 데이터 파일을 넣었을 때 구조와 품질을 빠르게 검수하는 도구를 추가합니다.

초기 구조:

```text
src/data/intake/
  inspect_dataset.py
  registry.py
```

`inspect_dataset.py`가 할 일:

```text
CSV/XLSX 파일 읽기
컬럼 목록 출력
행 수 출력
좌표 후보 탐지
주소 컬럼 후보 탐지
결측 좌표 개수 출력
중복 좌표 개수 출력
geometry 후보 추정
registry 등록 여부 확인
```

실행 예:

```bash
python -m src.data.intake.inspect_dataset src/data/raw/전국가로수길정보표준데이터.csv
```

출력 예:

```text
source_type: csv
rows: 12034
coordinate_candidates: 위도/경도
geometry_candidate: POINT
missing_coordinates: 32
duplicate_coordinates: 14
registry_status: not registered
recommendation: registry에 score/layer/profile 승인 필요
```

### 7. scoring_engine 일반화 설계 및 리팩토링

현재 `scoring_engine.py`는 score 이름이 수식에 하드코딩되어 있습니다. score가 늘어날수록 병목이 되므로 장기적으로 일반화가 필요합니다.

목표:

```text
profile이 사용할 score 목록과 효과를 정의하고,
scoring_engine은 그 목록을 순회하며 비용을 계산한다.
```

개념 공식:

```text
custom_score =
  length
  × penalty_factor들
  ÷ bonus_factor들
```

예시:

```text
bonus_factor = Π(1 + score_value × weight)
penalty_factor = Π(1 + score_value × weight)
custom_score = length × penalty_factor / bonus_factor
```

주의:

- `slope_score`처럼 모드별 효과가 다른 score는 일반 bonus/penalty로 단순화하지 않습니다.
- 리팩토링 전 회귀 테스트를 먼저 작성합니다.
- QA 담당과 테스트 기준을 맞춘 뒤 진행합니다.

### 8. profiles.py 확장 기준

새 profile은 아래 조건을 모두 만족할 때만 추가합니다.

```text
1. 대응하는 score 컬럼이 walk_edges에 존재한다.
2. score를 계산하는 collector가 존재한다.
3. score 의미와 cost effect가 score catalog에 정의되어 있다.
4. scoring_engine이 해당 score effect를 처리한다.
5. AI 응답에서 보장 가능한 표현이 정의되어 있다.
6. 팀이 registry에서 approved 처리했다.
```

예시:

```text
pet profile을 만들기 전 필요한 것:
- 반려동물 친화 데이터 출처
- pet_layer
- pet_score
- pet_score 계산 방식
- pet profile weight
- AI 응답 제한 문구
```

데이터가 없으면 profile을 만들지 않고, 사용자에게는 "현재 직접 보장할 수 없음"으로 안내합니다.

### 9. E 담당과 협업 양식

E가 새 데이터를 제안할 때 아래 양식으로 전달받습니다.

```text
데이터명:
출처:
source_type:
갱신 주기:
좌표 컬럼:
geometry:
추천 score:
score 효과: bonus / penalty / mode-specific
추천 profile:
데이터 품질 이슈:
AI 응답에 보장 가능한 표현:
```

채원 검토 결과는 아래 중 하나로 기록합니다.

```text
수용: registry 등록 및 collector 구현 진행
보류: 데이터 의미/품질/score 방향 추가 확인 필요
기각: 데이터 근거 부족 또는 profile 반영 불가
```

## PR 분할 계획

### PR 1. 문서화

제목:

```text
[Docs] 데이터 적재 및 score/profile 확장 규칙 정리
```

범위:

- 현재 데이터 파이프라인 정리
- 신규 데이터 추가 체크리스트 추가
- 현재 score 의미와 profile 매핑표 작성
- `slope_score` running 모드 동작 확인 항목 추가

### PR 2. 회귀 테스트

제목:

```text
[Test] scoring_engine 현재 동작 회귀 테스트 추가
```

범위:

- profile별 known edge custom_score 테스트
- blocked_tags 테스트
- running 모드 slope 동작 테스트

### PR 3. Intake MVP

제목:

```text
[Feat] 신규 데이터 검수용 intake inspector 추가
```

범위:

- `src/data/registry.yaml` 추가
- `src/data/intake/inspect_dataset.py` 추가
- CSV/XLSX 구조 분석
- 좌표/결측/중복/registry 등록 여부 리포트

### PR 4. scoring_engine 일반화

제목:

```text
[Refactor] scoring_engine score effect 기반 계산 구조로 개선
```

범위:

- score catalog 또는 registry 기반으로 bonus/penalty/mode-specific 처리
- 기존 테스트 통과 확인
- `slope_score` 정책은 팀 결정에 맞춰 반영

### PR 5. 시범 데이터 적용

제목:

```text
[Feat] 가로수길 데이터 nature_score 반영
```

범위:

- `전국가로수길정보표준데이터.csv` 검수
- registry 등록
- nature 계열 collector 확장 또는 별도 collector 추가
- `nature_score` 반영 방식 확인

## 당장 해야 할 일

1. 팀에 `slope_score` running 모드 정책 확인
2. `docs/data_ingestion.md`와 이 문서를 기준으로 신규 데이터 추가 체크리스트 합의
3. 현재 score/profile 매핑을 팀에 공유
4. scoring_engine 회귀 테스트 작성
5. `registry.yaml` 초안 작성
6. `inspect_dataset.py` MVP 작성
7. E에게 신규 데이터 제안 양식 공유
8. 우선순위 데이터를 1~3개로 좁히기

우선순위 후보:

```text
1. 전국가로수길정보표준데이터.csv → nature_score 또는 shade_score 후보
2. 서울 둘레길.csv → running_score 또는 landmark/scenic 후보
3. 실시간 혼잡도 데이터 → crowd_score 후보, 단 실시간 처리 구조 별도 논의 필요
```

## 완료 기준

이 작업은 아래 상태가 되면 1차 완료로 봅니다.

- 새 데이터가 들어왔을 때 팀원이 체크리스트로 검토할 수 있다.
- score 의미, 방향, profile 반영 기준이 문서화되어 있다.
- `scoring_engine.py` 현재 동작이 테스트로 고정되어 있다.
- registry를 통해 승인된 데이터와 미승인 데이터를 구분할 수 있다.
- intake inspector로 CSV/XLSX 신규 데이터의 기본 품질을 자동 확인할 수 있다.
- 데이터 근거 없는 profile이 추가되지 않도록 팀 규칙이 생겼다.
