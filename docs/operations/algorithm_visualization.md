# 알고리즘 시각화 실행

> 상태: Current
>
> 기준일: 2026-09-13
>
> 관련 코드: `visualizations/`, `benchmarks/runner/_astar_instrumented.py`, `artifacts/walk_graph_v1.*`

기존 경로 엔진을 실제로 실행해 그 탐색 과정을 재생하는 화면과 그림을 만든다. 이 문서
하나가 실행 방법·기록 형식·화면 규칙·검증 기준·관측 이력을 함께 담는다.

| 절 | 내용 |
|---|---|
| [1 목적과 범위](#1-목적과-범위) | 무엇을 만들고 무엇을 만들지 않는가 |
| [2 실행 방법](#2-실행-방법) | 명령과 옵션, 산출물, 기록 점검 |
| [3 구조](#3-구조) | 알고리즘 → 어댑터 → 화면, 검증 흐름 |
| [4 공통 이벤트 형식과 어댑터](#4-공통-이벤트-형식과-어댑터) | 기록 형식과 알고리즘별 매핑 |
| [5 재생 화면](#5-재생-화면) | 선택 화면, 자동 확대, 미니맵, 최종 경로 재생 |
| [6 검증](#6-검증) | 결과 보존, 형식 검사, 기록 불변식, 자가 점검 |
| [7 대표 사례와 제한](#7-대표-사례와-제한) | 성공·실패 사례와 확인 방법, 하지 않은 것 |
| [8 코드 위치](#8-코드-위치) | 파일별 책임 |
| [9 관측 이력](#9-관측-이력) | 날짜·커밋별 실행 관측 |
| [10 완료 기준 대조표](#10-완료-기준-대조표) | 이슈 #414 완료 기준과 근거 |

## 1. 목적과 범위

### 1.1 현재 범위

기존 Graph artifact를 읽어 상명대학교 서울캠퍼스 정문 입력 좌표와 실제로 연결할 도보망 노드를 PNG로 표시한다. 별도 `visualizations.routes` 명령은 기존 A*·편도 Beam·순환 Beam을 실행해 탐색 기록을 재생하는 HTML과 최종 경로 PNG를 만든다. `--with-grasp`로 GRASP 구축 및 Local·VND·VNS·ALNS 정제 4종을 추가한다. 2026-09-12부터 최단거리는 Haversine과 ALT 두 조건으로 각각 한 번씩 실행해 같은 반환 경로에서 탐색량이 얼마나 달라지는지 비교한다. GIF는 아직 포함하지 않는다.

정문 식별은 [상명대학교 서울캠퍼스 찾아오시는 길](https://www.sangmyung.ac.kr/kor/intro/road.do)의 “7016 버스는 학교 정문에서 하차” 안내를 기준으로 했다. 좌표는 2026-09-10에 Google 지도의 `상명대정문` 버스 정류장 위치를 확인하여 `visualizations/scenarios/sangmyung.json`에 기록했다.

### 1.2 입력과 출력

- 입력 도보망: `artifacts/walk_graph_v1.pkl`과 함께 있는 manifest·checksum
- 입력 시나리오: `visualizations/scenarios/sangmyung.json`
- 출력: `outputs/algorithm_visualization/sangmyung/{실행시각}/network.png`, `summary.json`

도보망은 `GraphArtifactRepository`가 해시·스키마·Python·NetworkX 호환성을 확인한 뒤 읽는다. DB, Valkey, 백엔드 서버, 외부 지도 타일은 사용하지 않는다.

## 2. 실행 방법

### 2.1 도보망 확인만

프로젝트 루트의 Git Bash에서 다음 명령을 실행한다.

```bash
./.venv/Scripts/python.exe -m visualizations.run --scenario sangmyung --network-only
```

표시 범위나 결과 폴더를 바꾸려면 다음 옵션을 사용한다.

```bash
./.venv/Scripts/python.exe -m visualizations.run \
  --scenario sangmyung \
  --network-only \
  --view-radius-m 2000 \
  --output-dir outputs/algorithm_visualization
```

`--view-radius-m`는 그림에 표시할 정사각형의 반폭이다. 목표 산책 거리나 알고리즘 탐색 반경이 아니다.

정상 실행하면 터미널에 데이터 버전, 전체 도보망 크기, 선택 노드, 연결 거리, 결과 파일의 절대 경로가 출력된다. 연결 거리가 30m를 넘으면 확대 이미지를 확인하라는 주의가 함께 나온다.

시나리오 `id`는 영문·숫자로 시작하는 영문·숫자·밑줄·하이픈 이름만 허용하며 Windows 예약 이름은 거부한다. 최종 결과 경로가 지정한 출력 폴더 내부인지 생성 전에 확인한다. 동일한 실행 폴더가 있으면 새 번호를 붙여 기존 결과를 보존한다.

`origin.coordinate_source_url`은 비어 있지 않은 HTTP(S) URL, `origin.verified_date`는 실제로 존재하는 `YYYY-MM-DD` 날짜여야 한다. 이 검사는 형식 검사이며 출처 내용과 좌표의 일치 여부는 별도로 확인해야 한다.

`summary.json`의 `displayed_node_count`는 전체 보기의 정사각형 안에 위치한 노드 수다. `displayed_edge_count`는 그 영역에 실제로 교차하는 연결 수이며, 바깥쪽 끝점은 노드 수에 포함하지 않는다. 선은 경계에서 잘라 표시한다.

### 2.2 이미지 읽는 방법

- 회색 선: 도보망 노드 사이의 연결
- 붉은 별: 지도에서 확인한 정문 입력 좌표
- 파란 테두리 원: 경로 알고리즘이 출발점으로 사용할 도보망 노드
- 점선: 두 위치 사이의 거리

왼쪽은 정문 주변 ±2km, 오른쪽은 정문 연결부를 확대한 그림이다. Graph artifact에는 상세 도로 곡선이 없으므로 노드 사이를 직선으로 표시한다. 실제 경로 거리에는 각 연결의 `length` 값을 사용해야 하며 화면상의 선 길이를 사용하지 않는다.

### 2.3 오류와 재시작 지점

| 오류 | 확인할 곳 |
|---|---|
| artifact·manifest·checksum 누락 | `artifacts/walk_graph_v1.*` 세 파일 |
| 해시 또는 버전 불일치 | artifact 세 파일이 같은 배포 묶음인지, Python·NetworkX 버전이 manifest와 맞는지 확인 |
| 시나리오 오류 | JSON 객체, 안전한 `id`, `origin.lat`, `origin.lon`, 유효한 출처 URL·확인일 |
| 결과 경로가 출력 폴더를 벗어남 | 시나리오 하위 폴더가 외부 경로로 연결돼 있는지 확인 |
| 300m 안에 연결 노드 없음 | 정문 좌표와 도보망 데이터 범위를 확인 |
| 표시 범위에 연결 없음 | `--view-radius-m`이 양수인지와 정문 좌표를 확인 |

입력 도보망을 다시 만들거나 DB를 재구축하지 않고, 위 입력·환경 문제를 수정한 뒤 같은 명령을 다시 실행한다.

### 2.4 실제 경로 탐색 재생

```bash
./.venv/Scripts/python.exe -m visualizations.routes --scenario sangmyung
```

Docker·서버·DB·인터넷 연결 없이 실행한다. 시나리오의 출발·도착 좌표를 기존 스냅 함수로 노드에 연결한 뒤, 전체 artifact 그래프에서 탐색한다. 표시 영역으로 그래프를 잘라 탐색하지 않는다.

경복궁역 도착점은 사용자 지정 **3번 출입구**다. 2026-09-10 [OSM node 3403538914](https://www.openstreetmap.org/node/3403538914)의 `description=경복궁역 3번출구`, `ref=3`, 좌표 `(37.5762348, 126.9726844)`를 공개 API에서 확인했다. 출처와 확인일은 시나리오에 저장한다.

| 요청 | 실제 실행 |
|---|---|
| 상명대 → 경복궁역 최단거리 | `OnewayAstarEngine.run()`, Haversine 휴리스틱 |
| 같은 요청 · ALT | `OnewayAstarEngine.run()`, 서비스 기동과 같은 방식으로 준비해 그래프에 붙인 ALT 휴리스틱 |
| 같은 목적지까지 우회 | `OnewayBeamEngine.run()`, 목표 = 측정한 최단거리 + 1km |
| 상명대에서 3km 순환 | `CircularBeamEngine.run()` |
| 상명대에서 그냥 3km | 기존 `extraction.yaml`의 목적지 없는 거리 요청 → 순환 규칙에 따라 위 기록을 재사용 |

마지막 행은 시각화에 입력 매핑을 명시한 것으로, LLM을 호출해 실제 자연어 해석을 검증한 결과는 아니다.

목표는 `--target-km 3`(순환), `--detour-extra-km 1`(최단거리에 더할 편도 거리)로 바꾼다. 모두 양의 유한한 값이어야 한다. ALT 조건은 `--alt-method planar|random`, `--alt-k`, `--alt-seed`로 바꾸며 기본값은 서비스 기본 설정과 같은 `planar`/`8`/`0`이다(같은지는 회귀 테스트가 대조한다). 기본 출력은 `outputs/algorithm_visualization/routes/sangmyung/{실행시각}/`이다.

- `routes.html`: 더블클릭해 브라우저에서 열고 상황 선택 → 재생·다음 단계·슬라이더로 확인. 외부 라이브러리·지도 타일 요청 없이 동작한다.
- `routes.png`: 세 시나리오의 최종 경로. 굵은 선이 대표 후보다.
- `trace.json`: 탐색 상태, 반환 노드열, 엔진 응답, 좌표 출처, 데이터·코드 버전, 입력 파일 해시.
- `summary.json`: 긴 탐색 기록을 제외한 검증·경로 지표.
- `checks.json`: 기록 불변식 점검 결과(항목별 통과 여부와 위반 내용). 6.3 참고.

### 2.5 GRASP·지역 개선 예제 추가

```bash
./.venv/Scripts/python.exe -m visualizations.routes --with-grasp --grasp-iterations 4 --seed 42
```

기본 세 엔진에 `WaypointEngine(construction="grasp", refinement=...)`의 `none`, `local`, `vnd`, `vns`, `alns` 다섯 가지를 추가한다. 모두 상명대에서 3km 순환, 경유지 2개, 거리 모드로 실행한다. 이 계열은 원래 거리 모드를 지원하므로 비용 함수 교체 없이 실제 `run()`을 호출한다. 방향 다양성·최소 경유지 간격·재통행 비교·경로 정리는 기존 코드 그대로다.

예제 재시작은 4회(기존 엔진 기본 24회), seed는 42다. `--grasp-iterations 24`로 기존 재시작 수를 사용할 수 있다. 다른 GraspConfig 값과 ALNS·VNS 설정은 기존 기본값을 유지한다. 재시작 수는 VNS 내부 교란·ALNS 내부 반복 횟수가 아니다. 정제가 난수를 소비하므로 같은 seed라도 첫 구축 이후의 초기 경로는 알고리즘별로 달라질 수 있다. 이 예제 결과만으로 성능 우열을 판단하지 않는다.

### 2.6 기록 점검

`visualizations.routes`는 실행 끝에 기록 불변식을 스스로 점검하고 `checks.json`을 남긴다. 같은 점검을 나중에 결과 폴더만 가지고 다시 돌릴 수도 있다.

```bash
./.venv/Scripts/python.exe -m visualizations.checks outputs/algorithm_visualization/routes/sangmyung/<실행시각>
./.venv/Scripts/python.exe -m visualizations.checks outputs/algorithm_visualization/routes/sangmyung/<실행시각> --artifact artifacts/walk_graph_v1.pkl
```

`--artifact`를 주면 장면에 적힌 거리를 실제 엣지 길이로 다시 잰다. 점검 항목과 실패 의미는 6.3에 있다.

### 2.7 옵션 요약

| 옵션 | 뜻 | 기본값 |
|---|---|---|
| `--scenario` | 시나리오 파일 이름(`visualizations/scenarios/`) | `sangmyung` |
| `--artifact` | 입력 도보망 artifact 경로 | `artifacts/walk_graph_v1.pkl` |
| `--target-km` | 순환 목표 거리 | `3.0` |
| `--detour-extra-km` | 편도 목표 = 측정한 최단거리 + 이 거리 | `1.0` |
| `--with-grasp` | GRASP 구축과 Local·VND·VNS·ALNS 정제 4종 추가 | 꺼짐 |
| `--grasp-iterations` | GRASP 재시작 수(기존 엔진 기본은 24) | `4` |
| `--seed` | GRASP 계열 난수 seed | `42` |
| `--alt-method` | ALT 랜드마크 선택법(`planar`·`random`) | `planar` |
| `--alt-k` | ALT 랜드마크 개수(Planar는 섹터 수라 실제 개수가 더 적을 수 있음) | `8` |
| `--alt-seed` | Random 선택법 seed | `0` |
| `--output-dir` | 결과 폴더의 상위 경로 | `outputs/algorithm_visualization/routes` |

`--alt-*` 기본값은 서비스 기본 설정(`WALK_ALT_METHOD`·`WALK_ALT_K`·`WALK_ALT_SEED`)과 같으며, 같은지는 회귀 테스트가 대조한다.

## 3. 구조

### 3.1 알고리즘에서 화면까지

알고리즘마다 기록 방식이 다르지만, 어댑터를 지나면 모두 같은 이벤트 형식이 된다. 화면과 점검기는 그 공통 형식만 본다 — 엔진 내부 변수명이나 줄 번호를 참조하지 않는다.

```mermaid
flowchart LR
  subgraph engines["알고리즘 · src/route_engine (시각화가 수정하지 않음)"]
    astar["OnewayAstarEngine<br/>+ALT 휴리스틱<br/>서비스 엔진"]
    beam["CircularBeamEngine<br/>OnewayBeamEngine<br/>서비스 엔진"]
    grasp["WaypointEngine<br/>GRASP·Local·VND·VNS·ALNS<br/>벤치마크 전용"]
  end
  subgraph adapters["기록 어댑터 · visualizations"]
    settrace["route_trace.py<br/>waypoint_trace.py<br/>settrace 수집 · 오프라인 전용"]
    astarad["astar_adapter.py<br/>실제 실행 → 재생 → 노드열 대조"]
    beamad["beam_adapter.py"]
    wpad["waypoint_adapter.py"]
    events["events.py<br/>validate_events · RunConditions"]
  end
  subgraph screen["장면과 화면 · visualizations"]
    story["route_story.py<br/>keyframes · stage_metrics"]
    view["route_view.py<br/>payload · catalog · landmarks"]
    html["routes.html<br/>자동 확대 · 미니맵 · final 애니메이션"]
    checks["checks.py<br/>기록 불변식 A~J"]
  end
  astar -->|"run 반환 경로"| astarad
  beam -->|"엔진 지역 상태"| settrace
  grasp -->|"엔진 지역 상태"| settrace
  settrace -->|"원본 이벤트 phase"| beamad
  settrace -->|"원본 이벤트 phase"| wpad
  astarad -->|"events 목록 + conditions"| events
  beamad -->|"events 목록 + conditions"| events
  wpad -->|"events 목록 + conditions"| events
  events -->|"검증을 통과한 events"| story
  story -->|"events + keyframes"| view
  view -->|"payload"| html
  html -->|"routes.html · trace.json · summary.json"| checks
```

`settrace` 수집은 Beam·GRASP 계열에만 남아 있고 오프라인 전용이다. 엔진 관찰자 훅이 승인되면 이 상자만 사라지고 어댑터 오른쪽은 그대로다([경로 엔진 관찰자 훅 도입 제안](../proposals/route_engine_trace_observer_proposal.md)).

### 3.2 한 실행의 검증 흐름

같은 입력을 기록을 켜고 한 번, 끄고 한 번 돌려 서로 대조하는 것이 출발점이다. 그 뒤로 형식 검사 → 장면 수치 → 화면 생성 → 기록 불변식 점검 → 브라우저 자가 점검이 이어진다.

```mermaid
flowchart TD
  rec["execute(record=True)<br/>기록 실행"]
  plain["execute(record=False)<br/>무계측 실행"]
  val["validate_events()<br/>공통 이벤트 형식"]
  cmp["compare_recording()<br/>반환 경로·응답 일치"]
  story["prepare_story()<br/>장면 수치·핵심 장면"]
  view["write_route_views()<br/>routes.html 생성"]
  checks["checks.py<br/>기록 불변식 10항목"]
  selfcheck["routes.html?selftest=1<br/>브라우저 자가 점검"]
  rec -->|"어댑터 반환 직전"| val
  val --> cmp
  plain --> cmp
  cmp --> story
  story --> view
  view --> checks
  checks -->|"통과해야 다음"| selfcheck
```

`compare_recording`이 어긋나면 그 자리에서 멈추고, `checks.py`가 위반을 찾으면 산출물은 남긴 채 `RuntimeError`로 멈춘다 — 무엇이 어긋났는지 `checks.json`에서 봐야 하기 때문이다.

## 4. 공통 이벤트 형식과 어댑터

### 4.1 기록과 비용 조건

`route_experiment.py`가 입력 그래프를 깊은 복사한 뒤 기존 엔진의 `run()`을 호출한다. 실행 컨텍스트 안에서만 Beam의 비용 함수를 `custom_score = length`로, 후보 다양화 벡터를 거리로 교체한다. 선호 가중치를 모두 0으로 설정하는 방식과 다르며, 이 실험은 기본 서비스 프로필 결과를 재현하는 것이 아니다. A*는 기존 거리 전용 계산을 그대로 쓴다.

재연결 시 기방문 노드 비용 5배, 목표 허용 오차 10%, 반복 노드 사이 짧은 구간 제거 등 기존 엔진의 탐색·정리 규칙은 유지한다. 따라서 ‘거리 기반’은 기본 엣지 비용을 말하며, 모든 탐색 판단이 거리 최소화 하나만 따르는 것은 아니다. 편도는 기존 최단 경로와의 겹침도도 비교한다.

`route_trace.py`는 엔진 소스를 복제하지 않고 Python trace로 Beam의 실제 로컬 상태를 읽는다. 확장 후보와 상위 최대 8개 유지 결과, 도착 연결, 후보 선택, 정리 전후를 기록한다. Beam 내부 재연결 A*의 세부 탐색은 완성 구간으로만 보여준다. 최단거리 A*는 2026-09-12부터 이 경로를 쓰지 않는다 — `astar_adapter.py`가 실제 실행을 재생해 기록한다(아래 “공통 이벤트 형식과 A*·ALT 어댑터” 절). 재생 시간은 계산 시간이 아니다.

Beam 계측 지점은 소스 구문을 검사해 찾고 함수 소스 해시를 결과에 남긴다. 해당 구조가 바뀌면 오류로 중단한다. Beam 기록은 디버거·커버리지와 동시에 실행하지 않는다. 원본 `src/**`와 의존 패키지 파일은 변경하지 않는다(A* 어댑터가 읽을 수 있도록 ALT 거리표를 휴리스틱 함수 속성으로 붙이는 한 줄은 예외이며, 엔진 동작·반환값은 그대로다).

`waypoint_trace.py`는 실제 함수의 다음 상태를 읽는다.

- GRASP: 제한 후보 목록(RCL), 선택 경유지, A*로 연결한 초기 경로.
- Local·VND: 변경 전 경로와 검토 후보(5개마다 표본), 실제 개선 채택(모두), VND 이웃 번호.
- VNS: 교란 레벨과 교란 후 경로, 이후 VND 개선 기록.
- ALNS: 일부 제거·재삽입한 경유지 순서, 내부 수락 판단, 도로 재연결 후 조립 계층의 최종 채택·기각.
- 전체: 최선해 갱신, 최종 정리와 반환 결과. 계측 과정은 추가 A*나 난수를 호출하지 않는다.

보라색 점선은 경유지 순서를 설명하며 실제 도로가 아니다. 도로로 복원된 경로는 실선으로 표시한다. ALNS 내부 수락과 조립 계층의 최종 채택은 별도 단계다. VND의 AlternativeSegment 이웃은 기존 코드에서 비활성이라 시각화에서도 나타나지 않는다.

### 4.2 공통 이벤트 형식 (2026-09-12)

알고리즘마다 기록 구조가 다르면 같은 화면에서 나란히 읽을 수 없다. 그래서 모든 알고리즘 어댑터가 같은 이벤트 형식으로 기록하도록 `visualizations/events.py`를 단일 기준으로 두었다. 이번 변경은 그 형식과 최단거리 A*·ALT 어댑터까지다. Beam·GRASP 계열 어댑터와 재생 화면 개편은 아직 하지 않았다.

#### 이벤트 키

| 키 | 필수 | 형 | 뜻 |
|---|---|---|---|
| `seq` | 필수 | int | 0부터 1씩 증가하는 단계 순서 |
| `kind` | 필수 | str | 아래 공통 어휘 중 하나 |
| `algorithm` | 필수 | str | 어댑터가 정하는 알고리즘 식별자(A* 어댑터는 `astar`) |
| `phase` | 필수 | str | 기존 재생 화면이 설명 문구를 고르는 세부 단계명 |
| `paths` | 필수 | list[list] | 이 장면과 관련된 경로 노드열 목록(없으면 `[]`) |
| `candidate_id`·`parent_candidate_id` | 선택 | str | 같은 후보의 흐름을 잇는 식별자 |
| `nodes` | 선택 | list | 이 장면과 관련된 노드 목록 |
| `values` | 선택 | dict | 판단에 쓴 수치. 화면이 그대로 표시할 수 있는 값만 |
| `decision` | 선택 | dict | `{"accepted": bool, "reason": str}` |
| `focus` | 선택 | dict | `{"nodes": [...]}` 자동 확대에 쓸 관심 노드(PR-C에서 사용) |

`current`·`frontier`·`popped`·`tree`·`explored`·`before` 같은 기존 키는 화면 호환을 위해 그대로 허용한다. `values`의 최상위에는 숫자·문자열·리스트(또는 `None`)만 담고, 리스트 항목은 스칼라이거나 한 겹 dict(표 한 줄)까지만 허용한다. `inf`·`nan`은 거부한다 — JSON으로 나가면 화면의 `JSON.parse`가 실패하기 때문이며, 숫자로 표시할 수 없는 자리는 `None`으로 남긴다.

`kind` 어휘는 다음 8개다. 어댑터는 여기 없는 이름을 쓰지 않는다.

| kind | 뜻 |
|---|---|
| `run_start` | 실행 시작. 입력과 조건을 알린다 |
| `candidates` | 이번 단계에서 만들어진 후보 목록 |
| `evaluate` | 후보를 평가했다(채택 여부는 아직 아님) |
| `select` | 후보를 골랐다 |
| `reject` | 후보를 버렸다 |
| `route_changed` | 현재 경로가 실제로 바뀌었다 |
| `cleanup` | 기존 정리 규칙을 적용했다 |
| `final` | 엔진이 반환한 결과 |

`validate_events()`가 seq 연속성, kind 어휘, 필수 키, `paths` 구조, `values` 타입, `decision`·`focus` 구조와 “`run_start`로 시작해 `final`로 끝나는가”를 검사한다. 어긋나면 `ValueError`로 멈춘다. 어댑터는 결과를 돌려주기 전에 반드시 이 함수를 통과시킨다.

#### 실행 조건(RunConditions)

결과마다 하나씩 붙는다. 화면과 문서가 “무엇을 어떤 조건으로 돌린 기록인가”를 이 값으로 읽는다.

| 항목 | 내용 |
|---|---|
| `code_commit` | 실행 시점의 `git rev-parse HEAD` |
| `artifact` | `{data_version, sha256}` — 입력 도보망 식별 |
| `algorithm`·`engine_class`·`mode` | 알고리즘 식별자, 실제 엔진 클래스, 결과 구분 이름 |
| `heuristic` | `{name, method, k_requested, k_actual, seed, landmarks, select_s, table_s}`. Haversine이면 `name="haversine"`에 나머지는 `None` |
| `target_m`·`seed`·`config` | 목표 거리, 실행 seed, 어댑터 설정 |
| `weight_policy` | 비용 규칙을 적은 문장(기본 비용, 차단 태그, 재방문 배수, 이번 실행의 `visited_nodes`) |

`heuristic.landmarks`는 `{node, lat, lon}` 목록이다.

### 4.3 A*·ALT 어댑터 절차

`visualizations/astar_adapter.py`는 세 단계로 기록한다.

1. **실제 실행**: `OnewayAstarEngine.run()`을 계측 없이 서비스와 똑같이 한 번 돌린다. `find_path`를 인스턴스 속성으로 감싸 `(start, end)` 인자만 캡처하고 원본 호출은 그대로 둔다.
2. **재생**: 같은 그래프·같은 휴리스틱(`engine._active_heuristic`)·같은 비용 함수로 계측판 A*(`benchmarks/runner/_astar_instrumented.py`)를 다시 돌린다. 계측판에 넣은 관찰자 훅이 큐에서 꺼낸 시점·넣은 시점·건너뛴 이웃을 알려 주고, 어댑터가 그것을 이벤트로 만든다.
3. **일치 확인**: 재생 경로가 엔진 반환 경로(`engine.last_path_nodes`)와 **노드열까지** 같은지 확인한다. 다르면 `TraceMismatchError`로 중단하고 장면을 만들지 않는다.

재생이 실제 탐색과 같다고 말할 수 있는 근거는 계측판이 `nx.astar_path`의 복제이기 때문이다. 우선순위 튜플에 단조 증가 카운터를 넣는 동점 처리까지 원본과 같아서 같은 입력에서 꺼내는 순서가 결정적으로 같다. 이 대조는 [PR #420](https://github.com/ChimaekMeeting/seoul-walk-platform/pull/420)에서 추가한 `tests/unit/test_alt_shortest_path_runner.py`가 지킨다. 회귀 테스트도 간선 길이가 모두 같아 동점이 많은 격자와 길이가 모두 다른 격자 양쪽에서 노드열 일치를 확인한다. 다만 계측판이 복제인 이상 NetworkX를 올릴 때는 두 파일을 다시 대조해야 한다.

이벤트 수는 `pop 수 + 2`다(`run_start` 1개 + pop마다 `select` 1개 + `final` 1개). 이웃 하나하나를 따로 장면으로 만들지 않고, 그 pop에서 확장하거나 건너뛴 이웃을 같은 장면의 `values["expanded"]`에 모아 넣는다. `select` 장면의 `values`에는 `g_m`·`h_m`·`f_m`, `h_kind`, 대기 상위 5개(`frontier_top`), ALT면 랜드마크별 하한 항(`h_terms`)과 가장 큰 항의 랜드마크(`best_landmark`)가 들어간다. `h_terms`의 최댓값이 그 장면의 `h_m`과 1e-6 안에서 같은지 매 장면 확인하고, 다르면 역시 중단한다.

엔진 내부에서 읽는 것은 `_active_heuristic`·`heuristic_name`·`blocked_tags`·`visited_nodes`뿐이다. 하나라도 없으면 “엔진 계약이 바뀌었습니다”라고 즉시 중단한다 — 조용히 다른 조건으로 재생하지 않기 위해서다. 재생 화면은 엔진의 변수명이나 줄 번호를 직접 참조하지 않는다. 화면이 읽는 것은 어댑터가 만든 공통 이벤트뿐이다.

#### settrace를 A*에서 걷어낸 이유

기존 `route_trace.SearchTrace`는 `sys.settrace`로 NetworkX 내부 프레임의 지역 변수를 읽었다. 디버거·커버리지와 같이 쓸 수 없고, 라이브러리의 줄 번호와 구문 구조에 묶이며, 모든 줄마다 파이썬 콜백이 걸린다. A*는 이제 재생 방식이라 이 제약이 없다. **Beam 계열은 아직 `settrace`를 쓴다** — 같은 방식의 어댑터로 옮기는 일은 PR-B에서 한다. 그래서 `SearchTrace`의 `settrace` 경로와 소스 해시 검사는 그대로 남아 있고, Beam 기록을 켠 실행은 여전히 디버거·커버리지와 동시에 돌리지 않는다.

#### 랜드마크를 화면 범위 계산에서 빼는 이유

ALT 랜드마크는 그래프 최대 연결요소의 바깥쪽 노드라 탐색 경로에서 아주 멀다. 2026-09-12 실행에서는 표시 중심에서 14~17km 떨어져 있었다. `route_view.event_nodes`가 화면 범위를 잡을 때 이 좌표까지 넣으면 경로가 몇 픽셀로 줄어든다. 그래서 랜드마크는 실행 조건과 화면 payload의 `landmarks`에만 넣고 이벤트의 `paths`·`nodes`에는 넣지 않는다. 재생 화면은 현재 보이는 영역 안에 들어올 때만 주황 마름모로 그린다. 기본 시나리오에서는 범위 밖이라 그려지지 않는다.

### 4.4 Beam·GRASP 계열 어댑터 (2026-09-12)

앞 절 “공통 이벤트 형식과 A*·ALT 어댑터”에서 만든 형식을 Beam·GRASP 계열까지 넓혔다. 이제 **모든 모드의 `trace`가 `validate_events()`를 통과한 공통 이벤트**이고, `conditions`(RunConditions)가 모든 결과에 붙는다. `route_story`·`route_view`·재생 화면은 settrace 산출물을 더 이상 직접 보지 않고 어댑터가 낸 공통 이벤트만 본다.

`sys.settrace` 수집(`route_trace.py`·`waypoint_trace.py`)은 이번에 걷어내지 않았다. 걷어내는 방법은 [경로 엔진 관찰자 훅 도입 제안](../proposals/route_engine_trace_observer_proposal.md)에 있으며, 승인 전까지는 "settrace 수집 → 어댑터 → 공통 이벤트"로 동작한다. 그래서 소스 해시 검사(`trace_source_hashes`)와 "디버거·커버리지와 동시에 실행하지 않는다"는 제약도 그대로다.

#### Beam 매핑 (`visualizations/beam_adapter.py`)

원본 키(`iteration`·`generated`·`kept`·`finished`·`before`)는 화면 호환을 위해 그대로 두고 공통 키를 덧붙인다.

| 원본 phase | kind | paths | 주요 values | decision |
|---|---|---|---|---|
| (없음) | `run_start` | `[[출발 노드]]` | `start`, `end`, `target_m`, `beam_width` | 없음 |
| `expand` | `candidates` | 생성된 확장 후보 전부 | `iteration`, `generated`, `kept`, `finished`, `candidate_ids`, `parent_candidate_ids` | 없음 |
| `keep` | `select` | 유지 후보 | 위와 같음 | `accepted=True`, "평가값 상위 N개 안에 들어 유지" |
| `keep`(차집합) | `reject` | 같은 반복의 `expand` − `keep` | 위 + `dropped` | `accepted=False`, "평가값 상위 N개 밖" |
| `connect` | `route_changed` | 연결된 완성 경로 | `connection`(순환이면 "출발지 복귀", 편도면 "도착 연결") | 없음 |
| `selection` | `select` | `find_path`가 반환한 후보 | `candidates` | `accepted=True`, "엔진 find_path가 반환한 후보입니다." |
| `prune` | `cleanup` | 정리 후 경로(`before`에 정리 전) | `removed_nodes` | 없음 |
| (없음) | `final` | 엔진이 반환한 경로 전부 | `candidates` | `accepted=True` |

탈락 후보 장면은 원본에 없는 새 장면이라 `phase="drop"`으로 만든다. 재생 화면에 같은 이름의 설명을 추가했다.

**판단 이유를 짓지 않는다.** 원본 기록에는 후보별 평가값 수치가 없다(상위 k개 절단만 기록된다). 그래서 `decision.reason`에는 순위 사실만 적고 점수를 만들어 내지 않는다.

#### GRASP 계열 매핑 (`visualizations/waypoint_adapter.py`)

| 원본 phase | kind | 비고 |
|---|---|---|
| (없음) | `run_start` | `seed`, `grasp_iters`, `num_waypoints`, `refinement` |
| `grasp_choice` | `candidates` + `select` | 제한 후보 목록(RCL)과 실제 선택을 두 장면으로 나눈다. select의 이유는 "제한 후보 목록(RCL) 안에서 무작위로 선택" |
| `constructed` | `route_changed` | `candidate_id=restart:{n}`, `values.distance_m` |
| `construction_failed` | `reject` | "구간 연결 실패로 구축 실패" |
| `neighbor` | `evaluate` | `values.sampled=True`(5개마다 표본), `examined`, `neighborhood`. decision 없음 |
| `improved` | `route_changed` | `accepted=True`, 원본 `objective_before`/`after`를 values에 편다 |
| `refinement_done` | `evaluate` | `changed`, `nodes_before`, `nodes_after`. 채택 판단은 `winner`가 한다 |
| `winner` | `select` | "전체 최선 갱신(RouteObjective 비교)." + 원본 비교 문장 |
| `shake` | `route_changed` | `shake_level`, `note="교란(VND 개선 전)"`. decision 없음 |
| `shake_failed` | `reject` | "교란 후보 생성 실패" |
| `vns_decision` | `select` / `reject` | 기록된 `accepted`를 따른다 |
| `destroy` / `repair` | `candidates` | `operator`, `stage`, `nodes`=경유지 |
| `alns_accept` | `evaluate` | **`select`/`reject`로 올리지 않는다**(아래) |
| `alns_result` | `select` / `reject` | 기록된 `accepted`를 따르고 재검증 수치를 values에 그대로 |
| `prune` | `cleanup` | 정리 전후 |
| (없음) | `final` | 엔진이 반환한 경로 |

`values`의 최상위에는 dict를 담을 수 없으므로 `objective_before`·`internal_after` 같은 한 겹 dict는 `objective_before_distance_error_m`처럼 이름만 펴서 넣는다. 값은 원본 기록의 숫자 그대로이며 새로 계산하지 않는다(`inf`는 `None`으로 남긴다). 회귀 테스트가 변환 전후 이벤트를 짝지어 "공통 `values`의 숫자가 원본 이벤트의 숫자이거나 원본이 담은 리스트 길이(또는 두 길이의 차)에서 나온 값인지"를 확인한다.

**경유지와 도로 경로를 섞지 않는다.** `nodes`에는 경유지 ID만, `paths`에는 도로 노드열만 넣는다. 경유지 단계 장면(`grasp_choice`·`destroy`·`repair`·`alns_accept`)의 `paths`는 항상 비어 있다.

### 4.5 내부 수락(alns_accept)과 최종 채택(alns_result)

`alns_accept`는 ALNS 내부 비용·온도 규칙의 판단이라 **나쁜 후보도 일시적으로 받아들인다.** 그래서 `evaluate`로만 남기고 `select`/`reject`로 올리지 않으며 `decision`을 붙이지 않는다. 실제로 경로에 반영되는 판단은 도로 경로로 다시 연결해 비교한 `alns_result`뿐이며 이쪽만 `select`/`reject`가 된다. 재생 화면도 두 장면의 설명 문구를 다르게 유지하고, 공통 단계(kind) 한 줄이 "후보를 평가했다(채택 여부는 아직 아님)"와 "후보를 골랐다/버렸다"로 갈린다. 이 구분은 회귀 테스트가 지킨다.

### 4.6 candidate_id 규칙

| 계열 | 규칙 |
|---|---|
| Beam | `beam:{반복 번호}:{노드열 sha1 앞 10자}`. `parent_candidate_id`는 직전 반복의 유지 후보 중 이 후보의 접두사인 가장 긴 노드열의 id(없으면 `None`) |
| GRASP | 뿌리는 `restart:{n}`. VNS·ALNS 내부 후보는 `restart:{n}:vns:{k}`·`restart:{n}:alns:{k}`, 이웃 검토는 그 아래 `:nb:{검토 순번}`. 정제 단계 이벤트는 뿌리를 `parent_candidate_id`로 갖는다 |

Beam에서 **같은 노드열이 여러 반복에 나타나면 반복 번호가 달라 id도 달라진다.** 의도한 것이다 — Beam은 반복마다 후보 집합을 새로 자르므로 "언제의 후보인가"가 후보의 정체에 포함된다.

GRASP의 `n`은 원본 기록의 `construction_call`, 즉 **구축 함수 호출 순번**이다. VNS의 전체 재구축(`waypoint_refinement._shake` level 4 이상)도 같은 함수를 부르므로 이 번호가 올라간다. 그래서 `n`은 "외부 재시작 번호"와 항상 같지는 않다.

### 4.7 변환할 수 없는 기록은 중단한다

모르는 `phase`, 필요한 키 없음, `expand`·`keep` 짝 불일치는 건너뛰지 않고 `TraceMismatchError`로 멈춘다(`visualizations/events.py`). 기록에 없는 장면을 만들어 내는 대신 실행을 실패시킨다.

### 4.8 service_use 판정 근거

`RunConditions.service_use`는 `"service"`(서비스 요청에 실제로 연결된 엔진) 또는 `"benchmark_only"`다. 이름이나 문자열 비교가 아니라 **`RouteService.base_engines`(서비스가 실제로 고르는 엔진 표)에 그 엔진 클래스가 있는지**로 정한다(`events.service_use_for`). 표는 `__init__`에서만 만들어지므로 인스턴스를 하나 세워 읽는다.

| 모드 | 엔진 | service_use |
|---|---|---|
| `shortest`, `shortest_alt` | `OnewayAstarEngine` | `service` |
| `detour` | `OnewayBeamEngine` | `service` |
| `circular` | `CircularBeamEngine` | `service` |
| `grasp_*` | `WaypointEngine` | `benchmark_only` |

서비스에 연결된 것은 `WaypointComposerEngine`이며 시각화가 쓰는 `WaypointEngine`(GRASP 조립)은 아직 서비스 경로에 없다. 비교표에는 "서비스 엔진"·"벤치마크 전용" 배지로, `routes.png` 제목에는 "(서비스)"·"(벤치마크)"로 표시한다.

### 4.9 배포에 남는 코드와 오프라인 전용 코드

- **배포에 남는다**: 엔진의 선택 인자(`OnewayAstarEngine`의 `heuristic=None`, 제안 중인 `observer=None`)는 정식 계약이다. 인자를 주지 않으면 기존 동작 그대로이고, 시각화·벤치마크만 넘긴다. 임시 계측이 아니므로 배포 전에 걷어내지 않는다.
- **오프라인 전용**: `visualizations/route_trace.py`·`waypoint_trace.py`의 `sys.settrace` 수집과 `benchmarks/runner/_astar_instrumented.py`의 계측 A* 복제본. 서비스 요청 중에는 켜지 않으며 `src/**`는 이 파일들을 import하지 않는다.

## 5. 재생 화면

재생 화면은 어두운 배경과 밝은 탐색 연결선을 사용한다. 상황마다 전체 탐색 범위에 맞춰 화면을 잡으며 `＋`/`－`·마우스 휠로 확대하고 드래그로 이동할 수 있다. `전체보기`는 해당 상황의 범위로 복원한다. A*의 확인한 연결은 NetworkX의 실제 부모 관계이며, 확인한 노드 사이에 있는 모든 도로를 탐색했다고 칠하지 않는다.

기본 명령으로 생성한 재생 화면에는 4개 실행 결과(최단거리 Haversine·ALT, 편도 우회, 순환)와 5개 요청 선택 항목이, `--with-grasp`로 생성한 화면에는 9개 실행 결과와 10개 요청 선택 항목이 들어간다(‘그냥 3km’는 순환과 같은 결과). 이미 생성한 HTML은 자체 데이터를 포함하므로 새 코드를 실행해 새로 생성해야 화면 변경이 반영된다.

### 5.1 결과 비교와 핵심 장면 읽기

새 화면은 순환 결과 비교표에서 시작한다. 현재 선택과 출발·복귀 조건 및 목표 거리가 같은 실행끼리 묶는다. 최단거리는 Haversine과 ALT가 같은 요청·같은 엔진이라 한 표에 두 행으로 묶고, 편도 우회는 별도 결과 표로 표시한다. 두 최단거리 행은 ‘방식’ 칸에 휴리스틱 조건을 함께 적어 구분한다. ‘그냥 3km’ 요청은 동일한 순환 결과를 재사용하므로 비교표에 중복 행을 만들지 않는다. 표의 과정 보기 버튼으로 해당 알고리즘을 선택한다.

- 비교표: 반환 첫 후보의 거리, 절대 목표 오차, 엔진별 허용 오차와 충족 여부, 재통행 비율, 실제 계산 시간. 재통행 비율은 이미 지난 무방향 엣지를 다시 걷는 거리의 합 / 전체 거리다. 경로 연결 실패와 목표 범위 밖을 구분한다.
- 시간: 기록을 끈 실행에서 `perf_counter()`로 `engine.run()` 직전부터 반환 직후까지 1회 측정한다. artifact 읽기, 그래프 깊은 복사, 엔진 생성, 계측 준비, 결과 검증과 그림 생성은 제외한다. `run()` 내부 전처리와 응답 생성은 포함한다. 반환 경로를 수집하는 얇은 prune 래퍼는 유지된다. 기록 실행 다음에 측정하므로 최초 실행 지연이나 반복 성능 벤치마크가 아니다. `run_seconds`는 기록 실행 자체에는 `None`, 저장 결과에는 무계측 실행의 초 단위 값을 사용한다.
- 핵심 장면: 사건 종류별 첫 장면과 마지막 상태, 실제 개선·전체 최선 갱신·전후 거리 변화, 수락·기각을 우선해 최대 26개를 고른다. A*는 도착점까지 직선거리가 처음 25/50/75% 줄어든 순간도 포함한다. 시간이나 단계 수를 균등 간격으로 나누지 않는다. 압축 때문에 모든 변화가 나타나는 것은 아니며, 전체 기록 번호와 생략 수를 표시한다.
- 전체 기록: 원래 기록을 그대로 재생한다. 다만 지역 개선의 후보 검토는 기존처럼 5개마다 표본이고 실제 개선은 모두 기록한다. ‘전체’가 모든 내부 함수 호출을 뜻하지 않는다.

장면 옆 수치는 실제 도보 엣지 길이로 다시 계산한다. 미완성 부분 경로에는 최종 목표 오차를 붙이지 않고, 도로로 연결하기 전의 경유지 점선에는 거리·재통행 수치를 만들지 않는다. 분홍색과 하늘색은 각각 이전 경로와 이 단계 결과 또는 검토 후보이며, 기각된 후보를 반환 경로로 해석하지 않는다.

`refinement_done`은 조립 계층이 호출한 같은 초기 후보의 개선 전후를 연결한다. 서로 다른 재시작의 첫 후보와 최종 승자를 임의로 묶지 않는다. `winner`는 이전 전체 최선과 새 전체 최선의 비교다. Local/VND 채택과 VNS 교란 후 판단은 실제 `RouteObjective` 비교값을 기록한다. 목표 범위 충족이 우선이며, 둘 다 범위 밖이면 거리 오차 → 재통행, 둘 다 안이면 재통행 → 거리 오차 순이다. 동률은 기존 경로를 유지한다.

ALNS 내부 수락은 평가값 변화와 온도에 따른 판단을 기록한다. 내부 최선과 현재 해는 별개이며 내부 수락이 최종 반영을 뜻하지 않는다. 도로 재연결 후에는 경유지 최소 간격, 연결 성공, RouteObjective 비교에 따라 반영하거나 유지한 이유를 따로 표시한다. 최종 정리 단계는 목표 오차 개선을 조건으로 실행되는 것이 아니므로, 정리 후 오차가 커져도 그대로 표시한다.

화면 변경과 기록 변경은 `visualizations/**` 및 이 실행 문서에 한정한다. 입력 도보망·기존 서비스 알고리즘·API 계약은 변경하지 않는다. 실패 복구는 출력 폴더의 `summary.json`과 `trace.json`에서 시작하며, 화면만 바꾸었어도 새 HTML을 생성해야 한다. DB나 Docker 기동은 필요 없다.

### 5.2 단계별 확대 재생 화면 (2026-09-13)

PR-A·B가 만든 기록 구조는 그대로 두고, 화면이 이미 있는 데이터(`kind`·`decision`·`focus`·`values`·`conditions`·`landmarks`·`keyframes`)를 실제로 쓰도록 재생 화면을 고쳤다. 기록 형식과 어댑터는 바꾸지 않았고 `src/`도 건드리지 않았다.

#### 파일 분리와 단일 산출물

유지보수는 세 파일로 한다.

| 파일 | 역할 |
|---|---|
| `visualizations/route_player.html` | 마크업. `__ROUTE_STYLE__`·`__ROUTE_SCRIPT__`·`__ROUTE_DATA__` 세 자리만 비워 둔다 |
| `visualizations/route_player.css` | 스타일 |
| `visualizations/route_player.js` | 동작 |

`route_view.render_player()`가 세 파일을 읽어 그 자리에 인라인하고 `routes.html` 하나를 만든다. **산출물은 여전히 외부 요청 없이 혼자 열리는 파일 하나다** — `<script src>`·`<link href>`를 만들지 않으며, 회귀 테스트가 생성된 문서에 그 두 패턴과 `http://`가 없는지 확인한다. 데이터의 `<`는 `<`로 바꿔 `<script>` 태그를 닫고 나가지 못하게 한다.

#### 선택 화면 ― 결과 선택과 새 실행의 구분

상단 "무엇을 볼지"에 **알고리즘 select(결과 선택)**, **테스트 상황 select(요청 문장)**, 읽기 전용 **시나리오 요약**, 선택한 결과의 **실행 조건 표**를 둔다.

- 알고리즘 항목 표시명은 `LABELS` + `settings`다(예: `최단거리 · A* + ALT · ALT Planar k=8 (실제 8개) · 서비스 엔진`). 같은 알고리즘이라도 설정이 다르면 별도 항목이며, 끝에 `service_use` 배지가 붙는다.
- 지원 목록(`payload.catalog`)은 코드에서 만든다. 최단거리 2건(Haversine·ALT) + 서비스 Beam 2건(순환·편도) + GRASP × `REFINEMENT_REGISTRY`의 모든 키다. 정제 목록은 손으로 적지 않고 `src/route_engine/engines/waypoint_engine_assembly`에서 읽는다(읽기만 하고 수정하지 않는다).
- `available`은 "이 파일에 그 모드의 결과가 있는가"다. `false`면 select에 `disabled`로 넣고 `· 새 실행 필요`를 붙이며, 아래 주황 상자에 직접 실행할 명령(`python -m visualizations.routes` 또는 `--with-grasp`)을 보여 준다. **화면은 실행을 시작하지 않는다.**
- 실행 조건 표에는 엔진, 휴리스틱(이름·선택법·요청/실제 랜드마크 수), 목표 거리, seed, 경유지 수·재시작 수·정제, 서비스 연결 배지, 코드 커밋 앞 7자, 도보망 `data_version`이 들어간다. 값은 전부 `RunConditions`에서 온다.

#### 실행 조건이 다른 행 경고

비교표 위 한 줄은 선택한 결과와 표의 다른 행을 `target_m`·`seed`·`num_waypoints`로 비교해 자동 생성한다. 하나라도 다르면 "실행 조건이 다른 행: … (같은 조건으로 비교하지 마세요)"를 띄운다. 비교는 `route_view.condition_differences()`가 파이썬에서 미리 계산해 `payload.condition_diff`로 넘기므로 화면과 테스트가 같은 규칙을 본다. 둘 다 값이 없는 항목(최단거리 두 건의 목표 거리)은 다르다고 보지 않는다.

### 5.3 자동 확대

카메라에 `auto`/`manual` 상태를 둔다. 기본은 `auto`다.

| 장면 | 카메라 목표 |
|---|---|
| `run_start` | 결과 전체 범위(`result.bounds`) |
| `final` | 반환 경로 좌표의 bbox + 여백 15% |
| 그 밖 | `event.focus.nodes` 좌표의 bbox + 여백 20% |

반지름은 항상 **최소 120m, 최대 `result.bounds.radius`**로 자른다. `focus`가 비어 있거나 좌표를 못 찾으면 카메라를 그대로 둔다(없는 범위를 만들지 않는다). 이동은 250ms 이하 ease-out 보간이며, 재생 중에는 속도 설정의 70%로 더 짧게 잡아 다음 장면과 겹치지 않게 한다. `prefers-reduced-motion`이면 보간 없이 즉시 옮긴다.

휠·드래그·`＋`·`－`·핀치·미니맵 클릭을 쓰면 `manual`로 바뀌고 지도 왼쪽 위에 "자동 확대 꺼짐"과 "자동 확대 켜기" 버튼이 나온다. **`전체보기`는 범위만 되돌리고 자동/수동 상태는 바꾸지 않는다.**

프레임 시계가 진행하지 않는 환경(headless 가상 시간 등)에서 애니메이션이 끝나지 않는 것을 막으려고 두 애니메이션 모두 프레임 수 상한(600프레임)을 둔다. 실제 브라우저에서는 60fps 기준 10초치라 시간이 먼저 찬다.

### 5.4 미니맵과 랜드마크 방향

지도 오른쪽 위에 작은 canvas(데스크톱 160px, 모바일 120px)를 얹는다. `result.bounds` 전체를 기준으로 배경 도보망(간격을 넓혀 4개마다), 출발·도착, 최종 장면의 반환 경로, 그리고 **지금 보고 있는 영역 사각형**을 그린다. 클릭하면 그 지점으로 카메라 중심이 옮겨진다(수동 전환).

ALT 랜드마크가 미니맵 범위 밖이면 가장자리에 화살표와 `L3 · 9.2km`처럼 방향·거리만 적는다. 거리는 payload의 랜드마크 좌표와 표시 중심에서 계산한 값이다. `랜드마크까지 보기` 버튼은 카메라를 `bounds ∪ landmarks`로 넓힌다(수동 전환). ALT 결과에서만 보인다.

### 5.5 kind별 색과 태그

설명 패널 맨 위에 `kind` 태그를 색으로 표시하고 그 아래 `decision.reason`을 굵게 적는다. 태그 문구와 색은 다음과 같다.

| kind | 태그 | 지도 표시 |
|---|---|---|
| `run_start` | 시작 | 경로를 그리지 않고 출발·도착 라벨과 "요청 조건" 상자만 표시 |
| `candidates` | 후보 | 주황 실선 |
| `evaluate` | 평가 | 하늘색 가는 선 + 변경 전 분홍. 설명에 "채택 아님" 명시 |
| `select` | 선택 | 하늘색 굵은 선 |
| `reject` | 기각 | 붉은 점선(`#ff7a7a`) + 같은 반복의 유지 후보를 얇은 하늘색으로 함께 표시 |
| `route_changed` | 경로 변경 | 변경 전 분홍 → 변경 후 하늘색 |
| `cleanup` | 정리 | 변경 전 분홍 → 정리 후 하늘색, 제거 노드 수 표시 |
| `final` | 결과 | 초록 실선(아래 애니메이션) |

기각 장면에 함께 그리는 "유지 후보"는 **직전 `select` 이벤트의 `paths`에서만** 가져온다(같은 `values.iteration`일 때). 없으면 그리지 않는다 — 없는 후보를 만들어 그리지 않기 위해서다.

A* 장면(`select` + `values.f_m`)에서는 현재 지점을 크게 그리고 `frontier_top` 5개의 `f` 값을 지도 위에 직접 적는다(라벨이 겹치면 생략). ALT면 `best_landmark` 방향으로 현재 지점에서 얇은 주황 점선을 그린다.

범례 첫 줄에는 **경유지(보라 점 W1…)·랜드마크(주황 마름모)·도로 경로(실선)** 세 가지 구분을 고정했다.

### 5.6 최종 경로 재생

`final` 장면에 들어가면(재생으로 도달하든 `최종 결과` 버튼이든) 카메라를 반환 경로 범위로 옮긴 뒤 **대표 후보(`paths[0]`)를 출발점부터 노드 순서대로 1.8초에 걸쳐 그린다.** 진행은 화면 거리가 아니라 좌표 거리에 비례한다. 다 그린 뒤에 추가 후보를 옅게 얹는다. 다른 장면으로 이동하면 즉시 취소하고, `다시 그리기` 버튼으로 반복한다. `prefers-reduced-motion`이면 처음부터 완성 상태로 보여 준다.

최종 장면에서는 이전 장면의 후보·대기 지점·탐색 트리를 절대 함께 그리지 않는다. **애니메이션 시간은 계산 시간이 아니다** — 화면 아래 문구에 그대로 남아 있다.

## 6. 검증

### 6.1 결과 보존과 실패 확인

각 실행은 계측을 켠 결과와 끈 결과의 노드열·응답을 비교한다. A* 거리는 Dijkstra와 대조한다. 반환 경로의 연결·출발·도착, 목표 거리 오차, 재통행률, 원본 그래프 속성·artifact 파일 보존을 확인한다. 그래프 라이브러리의 조회용 뷰 캐시는 데이터 보존 비교에서 제외한다.

경로가 나와도 목표 거리와 다를 수 있다. `route_valid`는 연결과 끝점만 검사하며 목표 합격과 별개다. 기존 Beam은 ±10%, 경유지 엔진은 GraspConfig의 ±5%를 적용해 재생 화면과 `target_within_tolerance`에 실패를 표시한다. `SUCCESS` 응답만으로 목표를 충족했다고 판단하지 않는다.

회귀 검증:

```bash
./.venv/Scripts/python.exe -m pytest visualizations/tests tests/unit/test_alt_runtime.py tests/unit/test_alt_shortest_path_runner.py -q --basetemp outputs/algorithm_visualization/tests
./.venv/Scripts/ruff.exe check visualizations benchmarks/runner/_astar_instrumented.py src/route_engine/alt_runtime.py
```

시각화가 쓰는 계측 A*와 ALT 거리표 부착은 `visualizations/` 밖에 있으므로 두 단위 테스트를 함께 돌린다.

문제가 생기면 `summary.json`의 조건과 `trace.json`을 먼저 확인한다. 계측 구조 오류는 `route_trace.py`의 대상 함수부터 대조한다. 기존 서비스 코드를 바꾸거나 DB를 재구축할 필요 없이 수정 후 같은 명령으로 새 결과 폴더를 생성한다.

### 6.2 공통 이벤트 형식 검사

모든 어댑터는 결과를 돌려주기 전에 `validate_events()`를 통과시킨다. 검사 항목과 거부
규칙은 4.2에 있다. 형식이 어긋나면 장면을 만들지 않고 `ValueError`로 멈춘다.

어댑터 입력이 어긋난 경우(모르는 원본 phase, 필요한 키 없음)는 그보다 앞에서
`TraceMismatchError`로 멈춘다(4.7). 두 경우 모두 "잘못된 장면을 만들어 보여 주는 것"보다
"멈추는 것"을 택한다.

### 6.3 기록 불변식 점검(checks.py)

`visualizations/checks.py`는 **엔진을 다시 돌리지 않고** 실행 결과 폴더만 읽어 "기록이 스스로 모순되지 않는가"를 본다. 결과 폴더만 있으면 나중에도, 다른 자리에서도 같은 점검을 돌릴 수 있다.

```bash
./.venv/Scripts/python.exe -m visualizations.checks <결과 폴더>
./.venv/Scripts/python.exe -m visualizations.checks <결과 폴더> --artifact artifacts/walk_graph_v1.pkl
```

결과는 `<결과 폴더>/checks.json`에 쓰고 위반이 하나라도 있으면 종료 코드 1이다. `visualizations.routes`도 실행 끝에 같은 점검을 부른다 — 위반이 있으면 `RuntimeError`로 멈추되 **산출물은 지우지 않는다**(무엇이 어긋났는지 `checks.json`과 `trace.json`에서 봐야 한다).

| 항목 | 보는 것 | 어긋나면 |
|---|---|---|
| A 형식 | 모든 기록이 `validate_events()`를 통과하고 `conditions`에 `algorithm`·`engine_class`·`mode`·`weight_policy`·`service_use`·`heuristic.name`이 있다 | 화면이 읽을 수 없는 기록이 만들어졌다 |
| B 순서 | `seq`가 0부터 연속, 첫 `kind`가 `run_start`, 마지막이 `final`, Beam 반복 번호가 뒤로 가지 않는다 | 장면 순서가 실제 탐색 순서와 다르다 |
| C 후보 연결 | `parent_candidate_id`가 앞선 장면에 실제로 있고, Beam은 부모 노드열이 자식의 접두사다. GRASP의 `restart:{n}` 뿌리는 `constructed`·`construction_failed`로 먼저 확정된다 | 같은 후보의 흐름을 잘못 이었다 |
| D 기각·유지 | 같은 반복의 유지·탈락이 겹치지 않고 합치면 확장 후보와 같다. `alns_accept`에서 온 장면은 `evaluate`뿐이다 | 검토 후보와 유지된 경로가 섞이거나, 내부 수락이 최종 채택처럼 보인다 |
| E 전후 수치 | 장면에 붙은 `stage_metrics`·`before_metrics`의 거리가 실제 엣지 길이와 1e-6 안에서 같다 | 화면 수치가 실제 도보망과 다르다 |
| F 최종 경로 | `final`의 대표 경로가 엔진 반환·응답 좌표 수와 같고, 고른 적 없는 후보 노드가 섞이지 않는다 | 버린 후보가 최종 경로에 섞였다 |
| G 비교표 일치 | `routes.html` payload의 `metrics`·`run_seconds`·`route_valid`·`settings`가 `summary.json`과 같다 | 비교표가 실제 실행과 다른 값을 보여 준다 |
| H 기록 보존 | `recording_preserves_result`·`route_valid`·`graph_unchanged`·`input_files_unchanged`가 모두 참이고, 최단거리는 `matches_dijkstra`도 참이다 | 기록이 결과를 바꿨거나 입력이 훼손됐다 |
| I 시간 구분 | 저장된 `run_seconds`가 무계측 실행 값이고(없거나 0 이하면 실패), 화면에 "계산 시간이 아닙니다" 문구가 있다 | 애니메이션 길이를 계산 시간으로 읽게 된다 |
| J 랜드마크 구분 | ALT 랜드마크 노드가 어떤 장면의 `paths`·`nodes`에도 들어 있지 않다 | 랜드마크가 경유지·도로 경로와 섞인다 |

E는 실제 엣지 길이가 필요해 `--artifact`를 줄 때만 돈다. 주지 않으면 그 항목만 `checks.json`에 "건너뜀"으로 남는다. `visualizations.routes` 안에서는 이미 읽어 둔 그래프를 그대로 넘기므로 항상 돈다.

`visualizations/tests/test_checks.py`는 정상 폴더에서 10개가 전부 통과하는 것뿐 아니라, 기록을 한 군데씩 일부러 깨뜨렸을 때 **의도한 항목만** 실패하는지 확인한다 — `seq` 건너뜀(A·B), `final` 누락(A·B), 유지 후보를 탈락에도 넣기(D), 내부 수락을 `select`로 올리기(D), 최종 경로에 후보 노드 섞기(F), 비교표 값 변조(G), 장면 거리 변조(E, 그래프를 줄 때만), 보존 플래그 거짓(H), 화면 문구 삭제(I).

### 6.4 브라우저 자가 점검

`routes.html?selftest=1`로 열면 화면이 모든 결과 × 전체 기록의 모든 장면을 순회하며 스스로를 점검하고, 결과를 `<pre id="selftest-result">`에 JSON으로 남긴다. 점검 항목은 여섯 가지다.

1. 순회 중 예외가 없다.
2. 자동 확대 반지름이 `[120m, bounds.radius]` 안이다.
3. 기각 장면에 같은 반복의 유지 후보가 있으면 함께 그려진다(그린 경로 수로 확인).
4. 최종 경로 애니메이션이 완료 상태(`progress === 1`)에 도달한다.
5. 선택 화면의 `disabled` 항목 수가 `catalog`의 `available=false` 수와 같다.
6. 미니맵 사각형이 현재 카메라와 일치한다.

```bash
./.venv/Scripts/python.exe -m pytest visualizations/tests/test_player_selftest.py -q
```

`test_player_selftest.py`가 toy 격자로 `routes.html`을 만든 뒤 Chrome headless로 데스크톱(1280×800)·모바일(390×844) 두 번 열어 실패가 0인지, 콘솔에 `Uncaught`가 없는지 확인한다. **Chrome 실행 파일이 없으면 건너뛴다** — 다른 개발 환경에서 이 파일 때문에 전체 테스트가 실패하지 않게 하기 위해서다. payload 생성 규칙(지원 목록·시나리오 요약·조건 차이·인라인)은 브라우저 없이 `test_route_view_payload.py`가 확인한다.

자가 점검은 프레임 시계에 기대지 않는다. 최종 경로 애니메이션은 같은 상태 전이를 그대로 밟도록 직접 끝까지 밀어 본 뒤 완료 여부를 본다 — headless 가상 시간에서는 `requestAnimationFrame`의 시각이 진행하지 않기 때문이다.

## 7. 대표 사례와 제한

### 7.1 읽는 법

아래 장면 번호는 **`outputs/algorithm_visualization/routes/sangmyung/20260913-011735` 실행의 전체 기록 번호**다. 재생 범위를 `전체 기록`으로 바꾼 뒤 슬라이더를 그 번호로 옮기면 같은 장면이 나온다. **수치는 이 입력 1회 실행의 관측이며 고정 기대값이 아니다** — 다른 seed·목표 거리·도보망에서는 달라진다.

### 7.2 성공 사례

**(1) 최단거리 Haversine vs ALT 비교**

- 실행: `./.venv/Scripts/python.exe -m visualizations.routes`
- 기대 화면: 비교표 "상명대 → 경복궁역 · 최단거리 결과"에 두 행이 뜨고 둘 다 `Dijkstra 일치`. 방식 칸에 휴리스틱 조건이 붙는다.
- 확인 방법: 두 행의 최종 거리가 같고(`3.541km`), `summary.json`의 `astar_queue_pops`가 Haversine `233`회 · ALT `83`회로 다르다. ALT 장면(`shortest_alt` 기록 2번)에서 `f = g + h`와 하한이 가장 큰 랜드마크, 화면 밖 랜드마크 방향 라벨을 볼 수 있다.
- 제한: 같은 경로를 더 적은 확장으로 찾았다는 것까지만 읽는다. `run_seconds`는 1회 측정이라 응답 시간 개선 폭의 근거가 아니다(6.1 참고).

**(2) 순환 Beam의 목표 범위 판정**

- 실행: `./.venv/Scripts/python.exe -m visualizations.routes`
- 기대 화면: `circular` 결과의 오른쪽 패널에 `목표 범위 벗어남 · 오차 439m`가 주황색으로 뜨고, 비교표 목표 판정 칸도 `범위 밖 (±10%)`이다.
- 확인 방법: 마지막 장면(기록 170번)의 반환 거리 `3.439km`와 목표 3.000km를 비교한다. `route_valid`는 참이다 — **연결·끝점 검증과 목표 합격은 별개**다.
- 제한: 목표를 못 맞춘 것은 이 입력에서 기존 Beam이 그렇게 동작한다는 관측이며, 알고리즘 우열 판단이 아니다.

**(3) GRASP + VND의 개선 채택 장면**

- 실행: `./.venv/Scripts/python.exe -m visualizations.routes --with-grasp --grasp-iterations 4 --seed 42`
- 기대 화면: `grasp_vnd` 기록 16번(`improved`, kind `route_changed`)에서 분홍색 변경 전 경로와 하늘색 채택 경로가 함께 보이고, 설명에 실제 `RouteObjective` 비교 문장이 붙는다.
- 확인 방법: 같은 장면의 `목표 오차`·`재통행` 전후 값이 둘 다 표시되는지, `evaluate`(검토만) 장면과 태그 색·문구가 다른지 본다.
- 제한: 검토 후보(`neighbor`)는 5개마다 표본이라 모든 검토가 장면으로 남지는 않는다. 실제 개선은 모두 남는다.

**(4) ALNS 내부 수락과 최종 기각의 구분**

- 실행: 위와 같음
- 기대 화면: `grasp_alns` 기록 9번은 태그가 `평가`(kind `evaluate`)이고 "내부 평가값 변화·온도"를 적는다. 기록 97번은 태그가 `기각`(kind `reject`)이고 도로 재연결 뒤 비교 결과를 적는다.
- 확인 방법: 두 장면의 공통 단계 줄이 각각 "후보를 평가했다(채택 여부는 아직 아님)"와 "후보를 버렸다"로 다른지 본다. `checks.py`의 D 항목이 `alns_accept`가 `select`·`reject`로 올라가지 않았는지 기계로 확인한다.
- 제한: 내부 수락은 ALNS 내부 비용·온도 규칙이라 나쁜 후보도 일시적으로 받아들인다. 이것을 최종 채택으로 읽으면 안 된다.

### 7.3 실패·경계 사례

**(5) GRASP 초기 경로 생성 실패**

- 실행: 위와 같음(재시작 수·seed에 따라 나타나지 않을 수 있다)
- 기대 화면: `construction_failed` 장면이 태그 `기각`으로 뜨고 "구간 연결 실패로 구축 실패"가 굵게 붙는다. 도로 경로는 그리지 않는다.
- 확인 방법: `summary.json`에서 해당 모드의 기록을 열어 `construction_failed` phase를 찾는다. 이번 실행에서는 `grasp_none` 기록 13번, `grasp_local` 16번, `grasp_vnd` 33번, `grasp_vns` 94·179·186·191번, `grasp_alns` 104·207번에 있었다.
- 제한: 실패 자체가 이 입력에서 늘 재현되지는 않는다. seed·재시작 수를 바꾸면 나타나거나 사라진다.

**(6) 목표 범위를 벗어난 결과 표시**

- 실행: 기본 명령
- 기대 화면: 순환 3km 요청의 관측 반환 거리 `3.439km`가 `범위 밖 (±10%)`으로 주황색 표시된다.
- 확인 방법: 비교표 목표 판정 칸과 오른쪽 패널 문구가 같은 판정을 보여 주는지 본다. `checks.py`의 G 항목이 비교표와 `summary.json`이 같은 값을 쓰는지 확인한다.
- 제한: 허용 오차는 방식마다 다르다(기존 Beam ±10%, 경유지 엔진 ±5%). 서로 다른 허용 오차를 같은 기준으로 비교하지 않는다.

**(7) 기록 구조 불일치 → `TraceMismatchError`로 중단**

- 재현: 어댑터가 모르는 원본 phase나 필요한 키가 없는 기록을 만나면 장면을 만들지 않고 멈춘다. 테스트로 재현한다.

```bash
./.venv/Scripts/python.exe -m pytest visualizations/tests/test_beam_adapter.py -k "unknown_source_phase or missing_key" -q
./.venv/Scripts/python.exe -m pytest visualizations/tests/test_waypoint_adapter.py -k "unknown_source_phase or missing_key" -q
```

- 기대: 두 테스트가 통과한다(즉, 깨진 기록에서 `TraceMismatchError`가 실제로 오른다). 화면은 잘못된 장면을 만들지 않는다.
- 제한: 이 감지는 어댑터 입력 단계에서만 작동한다. 엔진 코드 구조가 바뀌어 `settrace` 계측 지점을 못 찾으면 그보다 앞에서 `RuntimeError`로 멈춘다.

**(8) 지원하지 않는 조합 → 선택 화면 "새 실행 필요"**

- 재현: `--with-grasp` 없이 기본 명령으로 만든 `routes.html`을 연다.
- 기대 화면: 알고리즘 select에서 GRASP 5개 항목이 `· 새 실행 필요`로 흐리게 보이고 고를 수 없다. 아래 주황 상자에 `python -m visualizations.routes --with-grasp` 명령이 뜬다.
- 확인 방법: 자가 점검(6.4)이 "disabled 항목 수 == catalog의 available=false 수"를 확인한다. 화면은 실행을 시작하지 않는다 — 결과 선택과 새 실행을 문구·상자로 구분한다.
- 제한: 지원 목록은 `REFINEMENT_REGISTRY`에서 만들므로 엔진에 정제가 추가되면 자동으로 늘어난다. 반대로 목록에 있어도 그 조합을 실제로 돌려 본 적이 없으면 "새 실행 필요"로만 표시된다.

**(9) 계측 도구 충돌(디버거·커버리지) → `RuntimeError`**

- 재현: Beam·GRASP 기록은 `sys.settrace`를 쓰므로 디버거나 커버리지와 동시에 켤 수 없다. 이미 다른 trace가 걸려 있으면 `SearchTrace.__enter__`가 거부한다.

```bash
./.venv/Scripts/python.exe -m pytest visualizations/tests/test_route_experiment.py -k trace_restored -q
```

- 기대: "디버거·커버리지 trace를 끄고 시각화를 별도로 실행하세요." 메시지로 멈추고, 예외가 나도 이전 trace가 복원된다(위 테스트가 `sys.gettrace() is None`을 확인한다).
- 제한: 최단거리 A*는 재생 방식이라 이 제약이 없다. 엔진 관찰자 훅이 승인되면 Beam·GRASP도 없어진다.

### 7.4 제한 사항

- **실기기 모바일·터치 핀치 미검증.** headless의 390×844 뷰포트와 포인터 이벤트까지만 확인했다. 실제 단말에서의 핀치·스크롤 감각은 확인하지 않았다.
- **애니메이션 체감 속도 미검증.** headless 가상 시간에서는 `requestAnimationFrame` 시각이 진행하지 않아 자가 점검이 최종 경로 애니메이션을 직접 끝까지 밀어 상태만 확인한다. 실제 브라우저에서 1.8초에 걸쳐 그려지는 모습은 캡처로 확인되지 않는다.
- **`settrace`가 Beam·GRASP에 남아 있다.** 엔진 소스 구조가 바뀌면 계측이 깨지고 실행이 멈춘다(잘못된 장면을 만들지는 않는다). 대안은 [경로 엔진 관찰자 훅 도입 제안](../proposals/route_engine_trace_observer_proposal.md)에 있으며 아직 승인 전이다.
- **시나리오가 하나다.** 상명대 정문 → 경복궁역 3번 출입구만 실행한다. 다른 출발·도착이나 다른 도보망에서의 동작은 확인하지 않았다.
- **여러 seed 비교가 없다.** 모든 관측이 `--seed 42` 1회 실행이다. GRASP 계열은 난수를 쓰므로 seed를 바꾸면 결과가 달라진다. 알고리즘 우열의 근거로 쓸 수 없다.
- **챗봇 응답 연동이 없다.** 요청 문장과 모드의 대응은 기존 규칙을 시각화에 옮겨 적은 것이고, LLM을 호출해 실제 해석을 검증하지 않았다.
- **`tests/unit`의 기존 실패는 시각화와 무관하다.** 2026-09-13 기준 44건이며 전부 auth·banner·collector·graph_repository 영역이다. `tests/**`는 `visualizations`를 import하지 않는다.

## 8. 코드 위치

관련 구조 설명은 [PR #399](https://github.com/ChimaekMeeting/seoul-walk-platform/pull/399), ALNS 통합 도식은 [PR #404](https://github.com/ChimaekMeeting/seoul-walk-platform/pull/404), VNS 설정·VND 비활성 이웃 설명은 [PR #408](https://github.com/ChimaekMeeting/seoul-walk-platform/pull/408)을 참고한다. 시각화의 코드 위치는 다음과 같다.

| 파일 | 책임 |
|---|---|
| `visualizations/routes.py` | 시나리오 실행·계측 전후 비교·산출물 저장 |
| `visualizations/checks.py` | 결과 폴더만 읽어 기록 불변식 점검(A~J), `checks.json` 생성 |
| `visualizations/route_experiment.py` | 엔진 실행 조건과 경로 검증 |
| `visualizations/events.py` | 모든 어댑터가 쓰는 공통 이벤트 형식·실행 조건과 그 검사 |
| `visualizations/astar_adapter.py` | 최단거리 A*·ALT 실행의 재생과 노드열 대조 |
| `visualizations/beam_adapter.py` | 순환·편도 Beam 기록을 공통 이벤트로 변환 |
| `visualizations/waypoint_adapter.py` | GRASP 계열 기록을 공통 이벤트로 변환 |
| `visualizations/route_trace.py` | 기존 Beam 기록 수집(settrace, 오프라인 전용) |
| `visualizations/waypoint_trace.py` | GRASP·Local·VND·VNS·ALNS 기록 수집(settrace, 오프라인 전용) |
| `visualizations/route_story.py` | 장면별 경로 지표·변경 전후 비교·핵심 장면 선택 |
| `visualizations/route_view.py` | 기록을 화면 데이터·PNG로 변환, 세 파일을 합쳐 `routes.html` 생성 |
| `visualizations/route_player.html` | 재생 화면 마크업(스타일·스크립트·데이터 자리) |
| `visualizations/route_player.css` | 재생 화면 스타일 |
| `visualizations/route_player.js` | 재생 화면 동작(선택·자동 확대·미니맵·최종 경로 재생·자가 점검) |

## 9. 관측 이력

아래 관측은 모두 **해당 입력 1회 실행의 값**이며 고정 기대값이 아니다. 절 제목의 날짜와
코드 커밋이 그 관측의 기준이다.

### 2026-09-10 로컬 실행 관측

Windows, Python 3.12.14, NetworkX 3.6, artifact `v2-2026-08-25`에서 기본 명령으로 실행했다. 아래 값은 이 입력의 관측값이며 고정 기대값이 아니다. 재현 조건·기록은 `outputs/algorithm_visualization/routes/sangmyung/20260910-201257/summary.json`, `trace.json`에 있다(출력 폴더는 Git 제외).

| 시나리오 | 목표 | 반환 거리 | 판정 |
|---|---|---|---|
| 최단 | 없음 | 3540.573m | Dijkstra와 일치 |
| 편도 우회 | 4540.573m | 4510.774m, 4544.763m | 두 후보 모두 ±10% 안 |
| 순환 | 3000m | 3439.107m | +439.107m, ±10% 밖 |

세 경우 모두 계측 유무에 따른 반환 노드열·응답이 같고, 연결과 끝점 검증에 통과했다. 네트워크 연결을 차단한 실행이 완료됐으며 원본 그래프 데이터·입력 파일 해시가 보존됐다. 출발점 스냅 거리 3.323m, 도착점 스냅 거리 8.785m이며 표시 경로 거리는 스냅된 노드 사이 거리다.

시각화 회귀 테스트 39개 통과, Windows 심볼릭 링크 생성 권한 때문에 1개 건너뜀. Ruff 통과. Edge에서 재생·다음 단계·Beam 후보 유지·네 가지 상황 선택·최종 결과를 확인했고 외부 요청·JavaScript 오류가 없었다. 390px 화면에서 가로 넘침이 없음을 확인했다. 실제 챗봇 응답과 다른 알고리즘 후보 비교는 미검증이다.

### GRASP 추가 실행 관측 (2026-09-10)

앞 절과 같은 Windows/Python 3.12.14/NetworkX 3.6/artifact 환경에서 `--with-grasp --grasp-iterations 4 --seed 42`로 실행했다. 기록은 `outputs/algorithm_visualization/routes/sangmyung/20260910-204839/`의 `trace.json`, `summary.json`, `browser-check.json`에 있다. 아래는 해당 입력에서의 관측값이다.

| 3km 순환 방식 | 반환 거리 | ±5% 목표 판정 |
|---|---|---|
| GRASP 구축만 | 2162.983m | 범위 밖 |
| GRASP + Local | 2273.961m | 범위 밖 |
| GRASP + VND | 3129.551m | 범위 안 |
| GRASP + VNS | 3129.551m | 범위 안 |
| GRASP + ALNS | 2273.961m | 범위 밖 |

전체 8개 실행 결과에서 기록 유무에 따른 노드열·응답이 같고 연결·끝점 검증에 통과했다. 원본 그래프 속성·입력 파일 해시가 보존됐다. 기존 A*·Beam의 반환 거리는 앞 절 실행과 같았다. A*는 큐 추출 233회 전체, GRASP 구축은 경유지 선택과 구축 실패까지 기록했다. VNS 내부 재구축은 외부 재시작과 별도로 나타난다.

회귀 테스트 45개 통과·Windows 링크 권한으로 1개 건너뜀, Ruff 통과. Edge에서 9개 상황 선택, A*·Beam·VND·VNS·ALNS의 기록 단계, 재생, 확대, 드래그 이동, 전체보기와 390px 화면을 확인했다. JavaScript 오류·외부 네트워크 요청·모바일 가로 넘침이 없었다. VND/VNS의 목표 합격은 이 예제의 관측이며 전반적인 알고리즘 우열이나 최종 선정 근거는 아니다.

### 비교표·핵심 장면 검증 (2026-09-10)

Windows/Python 3.12.14/NetworkX 3.6, 같은 artifact에서 `--with-grasp --grasp-iterations 4 --seed 42`로 재실행했다. 최종 산출물은 `outputs/algorithm_visualization/routes/sangmyung/20260910-212602/`의 `routes.html`, `trace.json`, `summary.json`, `story-browser-check.json`이다. 아래 시간은 반복 평균이 아닌 해당 실행의 관측이다.

| 방식 | 전체 기록 → 핵심 장면 | 무계측 run 시간 |
|---|---|---|
| A* 최단 | 235 → 7 | 3.152초 |
| 편도 Beam | 72 → 11 | 2.560초 |
| 순환 Beam | 142 → 10 | 1.780초 |
| GRASP 구축만 | 20 → 13 | 3.681초 |
| GRASP + Local | 33 → 17 | 4.965초 |
| GRASP + VND | 83 → 19 | 7.148초 |
| GRASP + VNS | 181 → 26 | 10.325초 |
| GRASP + ALNS | 201 → 22 | 5.446초 |

8개 실행 모두 계측 전후 반환 노드열·응답이 같았으며, 연결·끝점 검증과 원본 그래프·입력 파일 보존을 확인했다. 반환 거리는 앞의 GRASP 추가 실행 관측과 같았다. VNS의 교란 후 재개선 판단 6회는 기존 해와 평가값이 같아 모두 기각이었다. ALNS 첫 재연결 후보는 거리 오차가 약 983.5m에서 1423.6m로 커져 기각됐고, 다른 재시작에서는 최소 경유지 간격 위반으로 유지한 이유가 기록됐다. 이를 알고리즘의 보편적 결과로 간주하지 않는다.

회귀 테스트 52개 통과, Windows 심볼릭 링크 권한으로 1개 건너뜀. Ruff와 `git diff --check` 통과. Edge에서 9개 상황의 모든 핵심 장면과 전체 기록 번호 대응, 모드 전환, 비교표 행 선택, 재생·확대·전체보기, ALNS 내부 수치·재검증 수치, 390px 모바일 배치를 확인했다. JavaScript 오류·외부 요청·문서 가로 넘침이 없었다. 데스크톱과 모바일 PNG를 직접 확인했다. 여러 seed·반복 실행 성능 순위 및 실시간 챗봇 응답은 이 검증에 포함하지 않는다.

### 2026-09-12 로컬 실행 관측

Windows, Python 3.12.14, NetworkX 3.6, artifact `v2-2026-08-25`, 코드 `755225b`에서 기본 명령(`python -m visualizations.routes`)으로 실행했다. 아래는 이 입력 1회 실행의 관측값이며 고정 기대값이 아니다. 기록은 `outputs/algorithm_visualization/routes/sangmyung/20260912-204441/`의 `summary.json`·`trace.json`에 있다(출력 폴더는 Git 제외).

| 최단거리 조건 | 큐 추출(popped) | 무계측 run 시간 | 반환 거리 | Dijkstra 대조 |
|---|---|---|---|---|
| Haversine | 233회 | 4.535초 | 3540.573m | 일치 |
| ALT Planar k=8(실제 8개) | 83회 | 4.804초 | 3540.573m | 일치 |

두 조건 모두 계측 유무에 따른 반환 노드열·응답이 같았고(`recording_preserves_result`), 연결·끝점 검증과 원본 그래프·입력 파일 해시 보존을 확인했다. 편도 우회 4510.774m·4544.763m, 순환 3439.107m로 앞 절 관측과 같았다.

ALT는 큐 추출을 233회에서 83회로 줄였지만 이 실행의 `run_seconds`는 오히려 조금 길었다. `run_seconds`는 `run()` 전체(16만 노드 그래프의 거리 전용 비용표 계산 포함)를 재는 값이라 탐색 자체의 비중이 작고, 1회 측정이라 머신 상태에 흔들린다. 여기서 읽을 수 있는 것은 “같은 경로를 더 적은 확장으로 찾았다”까지이며, 서비스 응답 시간 개선 폭은 이 수치로 판단하지 않는다. 휴리스틱별 탐색 시간 비교는 반복 측정을 하는 점대점 벤치마크(`benchmarks/runner/alt_shortest_path.py`)에서 본다.

ALT 준비(랜드마크 선정 1.178초 + 거리표 5.830초 = 7.382초)는 `run_seconds`에 포함하지 않고 `alt_prepare_seconds`로 따로 기록한다. 서비스는 이 준비를 기동 때 1회만 한다.

회귀 테스트 128개 통과, Windows 심볼릭 링크 권한으로 1개 건너뜀(`visualizations/tests`, `tests/unit/test_alt_runtime.py`, `tests/unit/test_alt_shortest_path_runner.py`). Ruff와 `git diff --check` 통과. Chrome 152 headless에서 생성된 `routes.html`을 열어 JavaScript 오류가 없음을 확인했고, 최단거리 비교표의 두 행과 휴리스틱 조건 표시, ALT 장면의 `f = g + h`·휴리스틱 종류·최대 하한 랜드마크·대기 상위 후보·이웃 처리 목록, 마지막 장면의 큐 추출·삽입 횟수가 나오는 것을 확인했다. 모바일 배치와 여러 seed·반복 실행 비교는 이번 검증에 포함하지 않았다.

`routes.png`는 결과가 4개가 되면서 2행 배치가 됐고, 2행 제목이 1행 x축 눈금과 겹쳐 보인다(`--with-grasp`의 기존 다행 배치와 같은 현상). 그림 배치 코드는 이번 범위에서 바꾸지 않았다.

### 2026-09-13 로컬 실행 관측

Windows, Python 3.12.14, NetworkX 3.6, artifact `v2-2026-08-25`, 코드 `aa61ea6`에서 `--with-grasp --grasp-iterations 4 --seed 42`로 실행했다. 아래는 이 입력 1회 실행의 관측값이며 고정 기대값이 아니다. 기록은 `outputs/algorithm_visualization/routes/sangmyung/20260913-000103/`의 `summary.json`·`trace.json`에 있다(출력 폴더는 Git 제외).

| 모드 | 이벤트 수 | kind 분포(`run_start`·`final` 각 1개 제외) | service_use | 계측 전후 결과 보존 | 경로 검증 |
|---|---|---|---|---|---|
| `shortest` | 235 | select 233 | service | 예 | 예 |
| `shortest_alt` | 85 | select 83 | service | 예 | 예 |
| `detour` | 85 | candidates 31 · select 32 · reject 13 · route_changed 5 · cleanup 2 | service | 예 | 예 |
| `circular` | 170 | candidates 44 · select 45 · reject 28 · route_changed 50 · cleanup 1 | service | 예 | 예 |
| `grasp_none` | 28 | candidates 8 · evaluate 3 · select 10 · reject 1 · route_changed 3 · cleanup 1 | benchmark_only | 예 | 예 |
| `grasp_local` | 41 | candidates 8 · evaluate 14 · select 10 · reject 1 · route_changed 5 · cleanup 1 | benchmark_only | 예 | 예 |
| `grasp_vnd` | 91 | candidates 8 · evaluate 62 · select 9 · reject 1 · route_changed 8 · cleanup 1 | benchmark_only | 예 | 예 |
| `grasp_vns` | 193 | candidates 12 · evaluate 132 · select 13 · reject 12 · route_changed 21 · cleanup 1 | benchmark_only | 예 | 예 |
| `grasp_alns` | 209 | candidates 128 · evaluate 62 · select 10 · reject 4 · route_changed 2 · cleanup 1 | benchmark_only | 예 | 예 |

Beam의 `candidates` 수는 `beam_iterations`와 같다(편도 31회, 순환 44회). 반환 거리는 최단 3540.6m, 편도 우회 4510.8m·4544.8m, 순환 3439.1m으로 앞 절 관측과 같고, GRASP 계열은 구축만 2163.0m / Local 2274.0m / VND·VNS 3129.6m / ALNS 2274.0m이었다. 원본 그래프와 입력 파일 해시가 보존됐다(`graph_unchanged`, `input_files_unchanged`).

`reject` 장면은 원본 `expand` 후보 중 탈락분을 다시 담으므로 `trace.json`이 커진다. 이 실행에서는 2.6MB였다.

회귀 테스트 177개 통과, Windows 심볼릭 링크 권한으로 1개 건너뜀(`visualizations/tests`, `tests/unit/test_alt_runtime.py`, `tests/unit/test_alt_shortest_path_runner.py`). Ruff와 `git diff --check` 통과.

브라우저 확인은 Chrome 152 headless에서 생성된 `routes.html`을 열어 했다. 처음 로드와, **10개 상황 × 전체 기록의 모든 장면 1307개를 실제 조작(상황 선택 `change`, 단계 슬라이더 `input`)으로 훑는 동안 JavaScript 오류가 0건**이었다. 그 과정에서 23개 `phase`와 8개 `kind` 전부가 화면에 표시됐다. 모바일 배치와 여러 seed·반복 실행 비교는 이번 검증에 포함하지 않았다.

### 2026-09-13 화면 확인 관측

Windows, Python 3.12.14, NetworkX 3.6, artifact `v2-2026-08-25`, 코드 `f792e37`에서 `--with-grasp --grasp-iterations 4 --seed 42`로 실행한 결과로 확인했다. 기록은 `outputs/algorithm_visualization/routes/sangmyung/20260913-003705/`에 있다(출력 폴더는 Git 제외). 아래는 이 입력 1회 확인의 관측이며 고정 기대값이 아니다.

| 항목 | 관측 |
|---|---|
| 결과 수 / 전체 장면 수 | 9개 / 1,137개 |
| 자가 점검(데스크톱 1280×800) | 2,334개 점검 전부 통과, 실패 0 |
| 자가 점검(모바일 390×844) | 2,334개 점검 전부 통과, 실패 0 |
| 브라우저 콘솔 | 두 화면 모두 `Uncaught` 0건 |
| 회귀 테스트 | 156개 통과, Windows 심볼릭 링크 권한으로 1개 건너뜀 |
| `routes.html` 크기 | 2.9MB(데이터 포함 단일 파일) |

Chrome 152 headless로 확인했다. 화면 상태별 캡처는 `outputs/algorithm_visualization/player-shots/20260913/`에 있다(선택 화면·비교표, 시작 장면, A*+ALT 선택 장면, Beam 기각 장면, 최종 경로 재생 완료). PNG는 커밋하지 않는다.

확인한 것: 선택 화면의 알고리즘 항목이 `LABELS + settings + 배지`로 나오고 새 실행이 필요한 항목이 `disabled`로 구분되는 것, 시나리오 요약과 실행 조건 표, 순환 비교표에서 GRASP 5행이 "경유지 수 다름"으로 경고되는 것, `run_start`의 요청 조건 상자, A*+ALT 장면의 `f` 라벨·랜드마크 방향 점선·미니맵 가장자리 거리 표시, Beam 기각 장면의 붉은 점선과 같은 반복 유지 후보, 최종 경로가 반환 경로 범위로 확대된 뒤 그려지는 것.

확인하지 못한 것: **실제 모바일 기기와 터치 핀치 확대는 실기기로 검증하지 않았다**(headless의 390×844 뷰포트와 포인터 이벤트까지만 확인). 애니메이션의 부드러움·체감 속도, 여러 seed·반복 실행 비교, 실제 챗봇 응답과의 대조도 이 확인에 포함하지 않았다. headless 가상 시간에서는 `requestAnimationFrame` 시각이 진행하지 않아 자가 점검이 최종 경로 애니메이션을 직접 끝까지 밀어 확인하므로, **실제 브라우저에서 1.8초에 걸쳐 그려지는 모습은 위 캡처(즉시 완성 상태)로는 확인되지 않는다.**

### 2026-09-13 검증·화면 다듬기 관측 (코드 `02e0f85`)

Windows, Python 3.12.14, NetworkX 3.6, artifact `v2-2026-08-25`, Chrome 152에서 `--with-grasp --grasp-iterations 4 --seed 42`로 실행했다. 기록은 `outputs/algorithm_visualization/routes/sangmyung/20260913-011735/`의 `summary.json`·`trace.json`·`checks.json`에 있다(출력 폴더는 Git 제외). 아래는 이 입력 1회 실행의 관측이며 고정 기대값이 아니다.

기록 불변식 점검은 실행 안에서 그래프를 그대로 넘겨 받아 10개 항목이 모두 돌았다.

| 항목 | 결과 | 위반 |
|---|---|---|
| A 형식 | 통과 | 0 |
| B 순서 | 통과 | 0 |
| C 후보 연결 | 통과 | 0 |
| D 기각·유지 | 통과 | 0 |
| E 전후 수치 | 통과 | 0 |
| F 최종 경로 | 통과 | 0 |
| G 비교표 일치 | 통과 | 0 |
| H 기록 보존 | 통과 | 0 |
| I 시간 구분 | 통과 | 0 |
| J 랜드마크 구분 | 통과 | 0 |

같은 폴더에 `--artifact artifacts/walk_graph_v1.pkl`을 주고 CLI로 한 번 더 돌려도 10개 항목이 모두 통과했다(E 포함).

| 확인 | 관측 |
|---|---|
| 결과 수 / 전체 장면 수 | 9개 / 1,137개 |
| 브라우저 자가 점검(데스크톱 1280×800) | 2,734개 점검 전부 통과, 실패 0 |
| 브라우저 자가 점검(모바일 390×844) | 2,734개 점검 전부 통과, 실패 0 |
| 랜드마크 방향 라벨 | 두 화면 모두 83개 장면에서 그려짐 |
| 브라우저 콘솔 | 두 화면 모두 `Uncaught` 0건 |
| 회귀 테스트 | 169개 통과, Windows 심볼릭 링크 권한으로 1개 건너뜀 |

반환 거리는 최단 3540.6m, 편도 우회 4510.8m·4544.8m, 순환 3439.1m, GRASP 계열은 구축만 2163.0m / Local 2274.0m / VND·VNS 3129.6m / ALNS 2274.0m으로 앞 절 관측과 같았다. 최단거리 큐 추출은 Haversine 233회, ALT 83회였다.

화면 다듬기 2건의 관측은 다음과 같다.

- **자동 확대 하한 200m**: 자가 점검이 A* 장면마다 카메라 반지름이 200m 이상인지 확인하고 전부 통과했다. 이전 하한(120m)에서는 첫 pop 장면처럼 focus 노드가 1개뿐일 때 주변 도보망이 거의 보이지 않았다. 캡처: `outputs/algorithm_visualization/player-shots/20260913-prd/05-astar-zoom-floor.png`
- **랜드마크 방향 라벨**: 점선이 화면을 벗어나는 장면에서 가장자리에 `L110931 방향 · 21.1km`처럼 붙는다. 캡처: `outputs/algorithm_visualization/player-shots/20260913-prd/06-landmark-direction.png`

- **미니맵 랜드마크 라벨 겹침 판정 수정**(2026-09-13, PR #425 점검 후): 라벨 시작점 사이 거리(22px)로 판정하던 것을 실제 글자 상자(측정 폭 × 12px, 여백 3px)의 교차로 바꿨다. 시작점이 23px 떨어져도 60px짜리 글자는 겹치던 문제다. 미니맵 밖으로 잘리는 글자도 생략한다. 자가 점검에 "장면마다 라벨 상자가 서로 겹치지 않는다" 검사를 추가해 같은 기록(`20260913-011735`)으로 화면만 다시 만들어 돌린 결과 데스크톱·모바일 각 3,871건 통과, 실패 0, 랜드마크 방향 라벨 83개 장면이었다. 회귀 테스트 169개 통과·1개 건너뜀은 변함없다.

PNG는 커밋하지 않는다. 실기기 모바일·터치 핀치와 애니메이션 체감 속도는 이번에도 확인하지 않았다(7.4).

## 10. 완료 기준 대조표

[이슈 #414](https://github.com/ChimaekMeeting/seoul-walk-platform/issues/414)의 완료 기준 6개를 근거와 함께 대조한다. 근거는 테스트 이름, `checks.py` 항목, 이 문서의 절, 결과 폴더 중 실제로 확인할 수 있는 것만 적는다.

| # | 완료 기준 | 상태 | 근거 |
|---|---|---|---|
| 1 | 지원 알고리즘의 실제 실행 기록으로 확대 설명부터 최종 경로 재생까지 이어진다 | 충족 | 9개 모드 전부 `run_start → … → final`이 한 기록으로 이어진다(`checks.py` B). 자동 확대는 5.3, 최종 경로 재생은 5.6. 브라우저 자가 점검이 모든 결과 × 모든 장면을 실제로 그려 본다(6.4). 결과 폴더 `outputs/algorithm_visualization/routes/sangmyung/20260913-011735` |
| 2 | 어떤 후보를 왜 선택하거나 기각했는지 확인할 수 있다 | 충족 | `decision.reason`이 화면 설명 맨 위에 굵게 붙는다(5.5). 이유는 기록에 있는 값과 기존 코드 규칙에서만 나온다 — `test_waypoint_adapter.py::test_decisions_are_explained_and_values_are_never_invented`가 "원본에 없는 수치"를 막는다. Beam은 평가값 수치가 원본에 없어 순위 사실만 적는다(4.5) |
| 3 | 경유지, ALT 랜드마크, 실제 도로 경로가 구분된다 | 충족 | 범례 첫 줄에 세 가지를 고정(5.5). 랜드마크가 경로·노드에 섞이지 않는지 `checks.py` J가 확인하고, 경유지와 도로 노드열이 섞이지 않는지 `test_waypoint_adapter.py::test_waypoint_ids_and_road_paths_are_never_mixed`가 확인한다. 화면 밖 랜드마크는 방향·거리 라벨로만 표시(5.4) |
| 4 | 같은 후보의 변경 전후와 서로 다른 실행 결과가 혼동되지 않는다 | 충족 | `candidate_id`·`parent_candidate_id`로 잇고(4.6), 부모가 실제 앞선 장면에 있는지와 Beam 접두사 관계를 `checks.py` C가 확인한다. 기각 장면에 같은 반복의 유지 후보를 함께 그려 구분한다(5.5, 자가 점검 ③). 서로 다른 실행 조건은 비교표 위 경고로 막는다(5.2) |
| 5 | 기록 기능이 반환 결과를 바꾸지 않으며, 기록을 사용하지 않는 실행도 유지된다 | 충족 | 모든 모드에서 기록을 켠 실행과 끈 실행의 반환 경로·응답을 대조한다(`compare_recording`, 6.1). `checks.py` H가 `recording_preserves_result`·`graph_unchanged`·`input_files_unchanged`·`matches_dijkstra`를 확인하고, 어댑터 테스트 4종이 `sys.gettrace() is None`과 `graph_digest` 보존을 확인한다 |
| 6 | 내부 구현이 바뀌었을 때 기록 어댑터를 중심으로 수정할 수 있다 | **부분 충족** | 화면·스토리·점검기는 공통 이벤트만 보고 엔진 변수명·줄 번호를 참조하지 않는다(3.1). 어댑터 입력이 바뀌어도 매핑표만 고치면 되도록 나눴다. **다만 Beam·GRASP는 아직 `settrace` 수집이라 엔진 소스 구조가 바뀌면 어댑터 앞단이 깨진다**(소스 해시 검사가 감지해 멈춘다). 이 앞단을 계약으로 바꾸는 일은 제안 상태이며 승인 전이다 |

### 대조 뒤에 남는 것

- 6번을 완전히 충족하려면 [경로 엔진 관찰자 훅 도입 제안](../proposals/route_engine_trace_observer_proposal.md)이 승인되고 구현돼야 한다. 그때 `route_trace.py`·`waypoint_trace.py`가 사라지고 어댑터 입력만 바뀐다.
- To-Do 7번의 "데스크톱·모바일에서 확대·이동·재생·설정 전환 검증"은 headless 두 화면 크기까지 확인했고 **실기기 검증은 남아 있다**(7.4).
- 위 표의 절 번호는 이 문서 기준이다. 실행 관측 수치는 9장에 날짜·커밋과 함께 있다.
