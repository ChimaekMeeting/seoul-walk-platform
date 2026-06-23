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

출력 예 (실제 구현, `src/data/intake/inspect_dataset.py`):

```text
[Intake Inspector]
file: src/data/raw/전국가로수길정보표준데이터.csv
source_type: csv
rows: 10333
columns_count: 18

[Candidates]
lat_candidates: ['가로수길시작위도', '가로수길종료위도']
lon_candidates: ['가로수길시작경도', '가로수길종료경도']
address_candidates: []
name_candidates: ['가로수길명', '도로명', '관리기관명', '제공기관명']
geometry_candidate: LINESTRING

[Quality]
missing_coordinates: 0
invalid_coordinates: 0
duplicate_coordinates: 1040
seoul_bbox_outliers: 9035

[Registry]
registry_status: registered
dataset_key: street_tree
approved: False
layer: undecided
score_column: undecided
score_effect: undecided
profiles: []
```

`seoul_bbox_outliers`가 9035/10333으로 매우 높은 것은 이 파일이 전국 데이터라는
뜻이고, 이는 registry의 `street_tree` 항목을 `approved: true`로 바꾸기 전에
서울 필터링이 먼저 필요하다는 신호로 해석합니다. inspector는 이 판단을 대신
내리지 않고 수치만 보여줍니다.

### 6.5. configured dataset vs adapter dataset

신규 데이터가 늘어날 때마다 `CSVSource.TAGS`, dispatch, `_load_xxx()`, collector를 계속 수정하는 구조는 데이터 1개당 코드 1세트를 새로 만드는 방식이라 유지보수 부담이 커집니다. 반대로 모든 데이터를 하나의 만능 추상화로 처리하려 하면 잘못된 추상화가 될 위험이 있습니다.

그래서 데이터셋을 두 종류로만 나눕니다.

**A. configured dataset**

- CSV/XLSX처럼 컬럼 기반으로 처리 가능한 정형 데이터입니다.
- `registry.yaml`에 컬럼 매핑과 필터 조건을 기록하면 공통 로더가 처리합니다.
- 데이터별 전용 함수를 새로 작성하지 않습니다.
- 필드 예시:
  - POINT 데이터: `lat_col`, `lon_col`
  - LINESTRING 데이터: `start_lat_col`, `start_lon_col`, `end_lat_col`, `end_lon_col`
  - 서울 필터: `city_filter_col`, `city_filter_value`
  - 이름/주소 컬럼: `name_col`, `address_col`
- 후보: `street_tree`(전국가로수길정보표준데이터.csv)

**B. adapter dataset**

- API, OSM, GeoJSON, 복잡한 전처리, 외부 호출, 하드코딩 로직이 필요한 데이터입니다.
- 데이터별 adapter/collector를 개별 구현합니다. 공통 로더로 강제로 합치지 않습니다.
- 현재 해당: Tour API landmark(`landmark_tour_api`), OSM 녹지(`osm_green_area`), Kakao API, 하천 GeoJSON(`river_geojson`), 러닝 코스 하드코딩 데이터(`running_park`, `bike_road`)

**공통화 기준**

공통화할 것:

```text
- intake inspector
- registry.yaml
- 컬럼 매핑
- 서울 필터 조건
- geometry 후보
- score/profile/AI expression 기록
- 승인 상태 approved
```

공통화하지 않을 것:

```text
- 데이터별 복잡한 전처리
- API 호출 방식
- OSM 태그 수집 방식
- 특수 geometry 변환
- profile 정책 판단
```

이 구분에 따르면 함수를 완전히 없앨 수는 없지만, 모든 신규 데이터마다 새 함수를 만들 필요도 없습니다. 표준 CSV/XLSX는 configured dataset으로 처리하고, 특수 데이터만 adapter dataset으로 남깁니다. AI는 raw 파일을 직접 고르지 않고, approved된 feature/score/ai_expression만 조합합니다.

### 6.6. registry.yaml 필드 확장 (configured dataset)

configured dataset은 `dataset_type: configured`와 컬럼 매핑 필드를 추가해 공통 로더가 바로 적재할 수 있게 합니다.

```yaml
street_tree:
  approved: false
  dataset_type: configured
  source_type: csv
  file: 전국가로수길정보표준데이터.csv
  geometry: LINESTRING
  start_lat_col: 가로수길시작위도
  start_lon_col: 가로수길시작경도
  end_lat_col: 가로수길종료위도
  end_lon_col: 가로수길종료경도
  city_filter_col: 제공기관명
  city_filter_value: 서울
  name_col: 가로수길명
  score_column: nature_score
  score_effect: bonus
  profiles:
    - nature
    - healing
  ai_expression: 가로수가 있는 길을 일부 반영할 수 있음
```

adapter dataset은 `dataset_type: adapter`만 추가하고, 기존처럼 `source`/`collector` 필드로 전용 구현을 가리킵니다.

### 6.7. 앞으로 구현할 intake/ingest CLI 방향

아직 구현하지 않으며, 방향만 문서화합니다.

**draft (구현됨, `src/data/intake/draft_dataset.py`)**

```bash
python -m src.data.intake.draft_dataset src/data/raw/전국가로수길정보표준데이터.csv
```

동작:

```text
- inspect_dataset.build_report() 결과를 먼저 출력한다.
- dataset_key, dataset_type(configured/adapter), feature, score_column,
  score_effect, profiles, ai_expression을 사용자에게 입력받는다.
- configured dataset이면 geometry, lat/lon 또는 start/end 좌표 컬럼,
  city_filter_col/value, name_col, address_col을 추가로 입력받는다.
  좌표/이름 후보가 감지되면 첫 번째 후보를 기본값으로 제안한다.
- adapter dataset이면 adapter, collector, layer를 추가로 입력받는다.
- registry.yaml에 approved: false로 draft 항목을 생성한다.
- 같은 dataset_key가 이미 있으면 --overwrite 옵션 없이는 덮어쓰지 않는다.
- DB는 변경하지 않는다.
```

실행 예 (입력값은 예시이며 실제로는 대화형으로 입력합니다):

```text
$ python -m src.data.intake.draft_dataset src/data/raw/전국가로수길정보표준데이터.csv
[Intake Inspector]
...
dataset_key: street_tree
dataset_type (configured/adapter) [configured]:
feature: nature
score_column: nature_score
score_effect (bonus/penalty/mode-specific/none) [none]: bonus
profiles (comma-separated): nature,healing
ai_expression: 가로수가 있는 길을 일부 반영할 수 있음
geometry [LINESTRING]:
start_lat_col [가로수길시작위도]:
start_lon_col [가로수길시작경도]:
end_lat_col [가로수길종료위도]:
end_lon_col [가로수길종료경도]:
city_filter_col: 제공기관명
city_filter_value: 서울
name_col [가로수길명]:
address_col:

Draft dataset saved:
- dataset_key: street_tree
- approved: False
- file: 전국가로수길정보표준데이터.csv
- score_column: nature_score
- score_effect: bonus

Next:
1. docs/data_intake_records.md에 검수/판단 기록을 남기세요.
2. 팀 승인 후 python -m src.data.intake.approve_dataset street_tree 를 실행하세요.
3. approved true 전까지 source_collector/data_collector에는 반영하지 않습니다.
```

이 도구는 layer/score/profile을 스스로 확정하지 않으며, 입력값을 그대로
"초안"으로 저장할 뿐입니다.

**approve (구현됨, `src/data/intake/approve_dataset.py`)**

```bash
python -m src.data.intake.approve_dataset street_tree \
    --decision "nature_score로 반영" \
    --reason "가로수길은 자연친화 근거로 사용 가능"
```

동작:

```text
- registry.yaml에서 approved: true로 변경하고 approved_at/decision/reason을 기록한다.
- docs/data_intake_records.md의 해당 dataset_key 섹션에 승인 기록을 추가한다.
- 이미 approved: true인 dataset은 --force 없이는 다시 승인하지 않는다.
- DB는 변경하지 않는다. 실제 적재는 ingest 단계에서 수행한다.
```

**preview (구현됨, `src/data/configured/preview.py`)**

approved: true, dataset_type: configured인 dataset을 registry.yaml 설정만으로
읽고 정제한 결과를 DB에 적재하기 전에 미리 확인합니다.

```bash
python -m src.data.configured.preview street_tree
```

동작:

```text
- registry.yaml에서 approved/configured/csv·xlsx 여부를 검증한다.
- 원본 파일을 읽어 city_filter, 좌표 결측/invalid 제거, 서울 bbox 밖 제거를 적용한다.
- POINT/LINESTRING 표준 record(wkt, properties)를 만들어 일부를 출력한다.
- DB는 변경하지 않는다.
```

**plan (구현됨, `src/data/configured/plan.py`)**

preview가 만든 record를 실제 csv_raw → layer → score → profile 파이프라인에
연결하기 전에, 무엇이 필요하고 어떤 schema 충돌이 있는지 보여줍니다.

```bash
python -m src.data.configured.plan street_tree
```

동작:

```text
- registry.yaml에서 approved/configured 여부를 검증한다.
- [Raw Plan] raw_table/query_key/source_file/geometry를 보여준다.
- [Layer Plan] score_column -> target_layer를 MVP 규칙으로 추정한다
  (nature_score -> nature_layer, safety_score -> safety_layer,
  running_score -> running_layer, child_score -> child_layer,
  landmark_score -> landmark_layer, 그 외는 undecided).
- target_layer가 csv_raw를 참조할 FK 컬럼(csv_raw_id)을 갖고 있지 않으면
  [Schema Warning]을 출력한다. 예: street_tree(csv_raw)는 nature_layer에
  연결하려 하지만 nature_layer는 현재 osm_raw_id만 가지고 있어 경고가 발생한다.
  해결 방법은 (1) target_layer에 csv_raw_id nullable 컬럼 추가, (2) raw id 없이
  저장, (3) 전용 layer를 별도로 만드는 것 중 하나이며, (1)을 권장한다.
- [Score Plan] score_column/score_effect/update_method(H3 log normalization)와
  함께, nature_score는 NatureRepository.get_nature_h3_counts()가 geom centroid
  기반이라는 경고를, LINESTRING geometry는 선 전체가 아니라 중심점 기준으로
  반영될 수 있다는 경고를 출력한다.
- [Profile Plan] registry의 profiles를 보여주고, profile은 score 조합이며
  healing_layer/healing_score 같은 새 layer/score를 자동 생성하지 않는다는
  점과, 해당 profile이 profiles.py에 실제로 존재하는지는 별도 확인이
  필요하다는 경고를 출력한다.
- [AI Expression] registry의 ai_expression과, 데이터 근거가 부족한 표현은
  사용하지 않는다는 안내를 출력한다.
- DB는 절대 변경하지 않는다. 마지막에 실제 반영 전 결정해야 할 항목
  (raw id 컬럼 추가 여부, 전용 layer 분리 여부, LINESTRING 집계 방식 등)을
  번호 목록으로 출력한다.
```

**ingest (plan 이후, 공통 로더 본체, 아직 구현되지 않음)**

```bash
python -m src.data.ingest street_tree
```

동작:

```text
- dataset_type이 configured이면 registry 컬럼 설정으로 공통 적재를 수행한다.
- dataset_type이 adapter이면 지정된 adapter를 호출한다.
- approved: true가 아니면 적재하지 않는다.
- plan에서 드러난 schema 충돌(raw id 컬럼 추가 등)을 먼저 해결해야 실행할 수 있다.
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
- `configured dataset`과 `adapter dataset` 구분이 문서에 명확히 추가되어 있다.
- 가로수길 데이터가 configured dataset 후보로 예시화되어 있다.
- registry.yaml이 단순 승인표가 아니라 공통 CSV/XLSX 적재 설정(컬럼 매핑, 서울 필터)으로 확장될 수 있음이 문서화되어 있다.
- approved configured dataset의 raw/layer/score/profile 반영 계획과 schema 충돌(예: street_tree → nature_layer의 csv_raw_id 부재)을 DB 변경 없이 미리 확인할 수 있다.
