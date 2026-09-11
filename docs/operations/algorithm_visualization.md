# 알고리즘 시각화 실행

> 상태: Current
>
> 기준일: 2026-09-10
>
> 관련 코드: `visualizations/`, `artifacts/walk_graph_v1.*`

## 현재 범위

기존 Graph artifact를 읽어 상명대학교 서울캠퍼스 정문 입력 좌표와 실제로 연결할 도보망 노드를 PNG로 표시한다. 별도 `visualizations.routes` 명령은 기존 A*·편도 Beam·순환 Beam을 실행해 탐색 기록을 재생하는 HTML과 최종 경로 PNG를 만든다. `--with-grasp`로 GRASP 구축 및 Local·VND·VNS·ALNS 정제 4종을 추가한다. ALT 비교와 GIF는 아직 포함하지 않는다.

정문 식별은 [상명대학교 서울캠퍼스 찾아오시는 길](https://www.sangmyung.ac.kr/kor/intro/road.do)의 “7016 버스는 학교 정문에서 하차” 안내를 기준으로 했다. 좌표는 2026-09-10에 Google 지도의 `상명대정문` 버스 정류장 위치를 확인하여 `visualizations/scenarios/sangmyung.json`에 기록했다.

## 입력과 출력

- 입력 도보망: `artifacts/walk_graph_v1.pkl`과 함께 있는 manifest·checksum
- 입력 시나리오: `visualizations/scenarios/sangmyung.json`
- 출력: `outputs/algorithm_visualization/sangmyung/{실행시각}/network.png`, `summary.json`

도보망은 `GraphArtifactRepository`가 해시·스키마·Python·NetworkX 호환성을 확인한 뒤 읽는다. DB, Valkey, 백엔드 서버, 외부 지도 타일은 사용하지 않는다.

## 실행

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

## 이미지 읽는 방법

- 회색 선: 도보망 노드 사이의 연결
- 붉은 별: 지도에서 확인한 정문 입력 좌표
- 파란 테두리 원: 경로 알고리즘이 출발점으로 사용할 도보망 노드
- 점선: 두 위치 사이의 거리

왼쪽은 정문 주변 ±2km, 오른쪽은 정문 연결부를 확대한 그림이다. Graph artifact에는 상세 도로 곡선이 없으므로 노드 사이를 직선으로 표시한다. 실제 경로 거리에는 각 연결의 `length` 값을 사용해야 하며 화면상의 선 길이를 사용하지 않는다.

## 오류와 재시작 지점

| 오류 | 확인할 곳 |
|---|---|
| artifact·manifest·checksum 누락 | `artifacts/walk_graph_v1.*` 세 파일 |
| 해시 또는 버전 불일치 | artifact 세 파일이 같은 배포 묶음인지, Python·NetworkX 버전이 manifest와 맞는지 확인 |
| 시나리오 오류 | JSON 객체, 안전한 `id`, `origin.lat`, `origin.lon`, 유효한 출처 URL·확인일 |
| 결과 경로가 출력 폴더를 벗어남 | 시나리오 하위 폴더가 외부 경로로 연결돼 있는지 확인 |
| 300m 안에 연결 노드 없음 | 정문 좌표와 도보망 데이터 범위를 확인 |
| 표시 범위에 연결 없음 | `--view-radius-m`이 양수인지와 정문 좌표를 확인 |

입력 도보망을 다시 만들거나 DB를 재구축하지 않고, 위 입력·환경 문제를 수정한 뒤 같은 명령을 다시 실행한다.

## 실제 경로 탐색 재생

```bash
./.venv/Scripts/python.exe -m visualizations.routes --scenario sangmyung
```

Docker·서버·DB·인터넷 연결 없이 실행한다. 시나리오의 출발·도착 좌표를 기존 스냅 함수로 노드에 연결한 뒤, 전체 artifact 그래프에서 탐색한다. 표시 영역으로 그래프를 잘라 탐색하지 않는다.

경복궁역 도착점은 사용자 지정 **3번 출입구**다. 2026-09-10 [OSM node 3403538914](https://www.openstreetmap.org/node/3403538914)의 `description=경복궁역 3번출구`, `ref=3`, 좌표 `(37.5762348, 126.9726844)`를 공개 API에서 확인했다. 출처와 확인일은 시나리오에 저장한다.

| 요청 | 실제 실행 |
|---|---|
| 상명대 → 경복궁역 최단거리 | `OnewayAstarEngine.run()` |
| 같은 목적지까지 우회 | `OnewayBeamEngine.run()`, 목표 = 측정한 최단거리 + 1km |
| 상명대에서 3km 순환 | `CircularBeamEngine.run()` |
| 상명대에서 그냥 3km | 기존 `extraction.yaml`의 목적지 없는 거리 요청 → 순환 규칙에 따라 위 기록을 재사용 |

마지막 행은 시각화에 입력 매핑을 명시한 것으로, LLM을 호출해 실제 자연어 해석을 검증한 결과는 아니다.

목표는 `--target-km 3`(순환), `--detour-extra-km 1`(최단거리에 더할 편도 거리)로 바꾼다. 모두 양의 유한한 값이어야 한다. 기본 출력은 `outputs/algorithm_visualization/routes/sangmyung/{실행시각}/`이다.

- `routes.html`: 더블클릭해 브라우저에서 열고 상황 선택 → 재생·다음 단계·슬라이더로 확인. 외부 라이브러리·지도 타일 요청 없이 동작한다.
- `routes.png`: 세 시나리오의 최종 경로. 굵은 선이 대표 후보다.
- `trace.json`: 탐색 상태, 반환 노드열, 엔진 응답, 좌표 출처, 데이터·코드 버전, 입력 파일 해시.
- `summary.json`: 긴 탐색 기록을 제외한 검증·경로 지표.

### 기록과 비용 조건

`route_experiment.py`가 입력 그래프를 깊은 복사한 뒤 기존 엔진의 `run()`을 호출한다. 실행 컨텍스트 안에서만 Beam의 비용 함수를 `custom_score = length`로, 후보 다양화 벡터를 거리로 교체한다. 선호 가중치를 모두 0으로 설정하는 방식과 다르며, 이 실험은 기본 서비스 프로필 결과를 재현하는 것이 아니다. A*는 기존 거리 전용 계산을 그대로 쓴다.

재연결 시 기방문 노드 비용 5배, 목표 허용 오차 10%, 반복 노드 사이 짧은 구간 제거 등 기존 엔진의 탐색·정리 규칙은 유지한다. 따라서 ‘거리 기반’은 기본 엣지 비용을 말하며, 모든 탐색 판단이 거리 최소화 하나만 따르는 것은 아니다. 편도는 기존 최단 경로와의 겹침도도 비교한다.

`route_trace.py`는 엔진 소스를 복제하지 않고 Python trace로 실제 로컬 상태를 읽는다. A*는 큐에서 꺼낸 매 지점과 실제 부모 연결·현재 경로, Beam은 확장 후보와 상위 최대 8개 유지 결과, 도착 연결, 후보 선택, 정리 전후를 기록한다. Beam 내부 재연결 A*의 세부 탐색은 완성 구간으로만 보여준다. 재생 시간은 계산 시간이 아니다.

계측 지점은 소스 구문을 검사해 찾고 함수 소스 해시를 결과에 남긴다. 해당 구조가 바뀌면 오류로 중단한다. 디버거·커버리지와 동시에 실행하지 않는다. 원본 `src/**`와 의존 패키지 파일은 변경하지 않는다.

### 검증과 실패 확인

각 실행은 계측을 켠 결과와 끈 결과의 노드열·응답을 비교한다. A* 거리는 Dijkstra와 대조한다. 반환 경로의 연결·출발·도착, 목표 거리 오차, 재통행률, 원본 그래프 속성·artifact 파일 보존을 확인한다. 그래프 라이브러리의 조회용 뷰 캐시는 데이터 보존 비교에서 제외한다.

경로가 나와도 목표 거리와 다를 수 있다. `route_valid`는 연결과 끝점만 검사하며 목표 합격과 별개다. 기존 Beam은 ±10%, 경유지 엔진은 GraspConfig의 ±5%를 적용해 재생 화면과 `target_within_tolerance`에 실패를 표시한다. `SUCCESS` 응답만으로 목표를 충족했다고 판단하지 않는다.

회귀 검증:

```bash
./.venv/Scripts/python.exe -m pytest visualizations/tests -q --basetemp outputs/algorithm_visualization/tests
./.venv/Scripts/ruff.exe check visualizations
```

문제가 생기면 `summary.json`의 조건과 `trace.json`을 먼저 확인한다. 계측 구조 오류는 `route_trace.py`의 대상 함수부터 대조한다. 기존 서비스 코드를 바꾸거나 DB를 재구축할 필요 없이 수정 후 같은 명령으로 새 결과 폴더를 생성한다.

### 2026-09-10 로컬 실행 관측

Windows, Python 3.12.14, NetworkX 3.6, artifact `v2-2026-08-25`에서 기본 명령으로 실행했다. 아래 값은 이 입력의 관측값이며 고정 기대값이 아니다. 재현 조건·기록은 `outputs/algorithm_visualization/routes/sangmyung/20260910-201257/summary.json`, `trace.json`에 있다(출력 폴더는 Git 제외).

| 시나리오 | 목표 | 반환 거리 | 판정 |
|---|---|---|---|
| 최단 | 없음 | 3540.573m | Dijkstra와 일치 |
| 편도 우회 | 4540.573m | 4510.774m, 4544.763m | 두 후보 모두 ±10% 안 |
| 순환 | 3000m | 3439.107m | +439.107m, ±10% 밖 |

세 경우 모두 계측 유무에 따른 반환 노드열·응답이 같고, 연결과 끝점 검증에 통과했다. 네트워크 연결을 차단한 실행이 완료됐으며 원본 그래프 데이터·입력 파일 해시가 보존됐다. 출발점 스냅 거리 3.323m, 도착점 스냅 거리 8.785m이며 표시 경로 거리는 스냅된 노드 사이 거리다.

시각화 회귀 테스트 39개 통과, Windows 심볼릭 링크 생성 권한 때문에 1개 건너뜀. Ruff 통과. Edge에서 재생·다음 단계·Beam 후보 유지·네 가지 상황 선택·최종 결과를 확인했고 외부 요청·JavaScript 오류가 없었다. 390px 화면에서 가로 넘침이 없음을 확인했다. 실제 챗봇 응답과 다른 알고리즘 후보 비교는 미검증이다.

## GRASP·지역 개선 예제와 가독성 개선

```bash
./.venv/Scripts/python.exe -m visualizations.routes --with-grasp --grasp-iterations 4 --seed 42
```

기본 세 엔진에 `WaypointEngine(construction="grasp", refinement=...)`의 `none`, `local`, `vnd`, `vns`, `alns` 다섯 가지를 추가한다. 모두 상명대에서 3km 순환, 경유지 2개, 거리 모드로 실행한다. 이 계열은 원래 거리 모드를 지원하므로 비용 함수 교체 없이 실제 `run()`을 호출한다. 방향 다양성·최소 경유지 간격·재통행 비교·경로 정리는 기존 코드 그대로다.

예제 재시작은 4회(기존 엔진 기본 24회), seed는 42다. `--grasp-iterations 24`로 기존 재시작 수를 사용할 수 있다. 다른 GraspConfig 값과 ALNS·VNS 설정은 기존 기본값을 유지한다. 재시작 수는 VNS 내부 교란·ALNS 내부 반복 횟수가 아니다. 정제가 난수를 소비하므로 같은 seed라도 첫 구축 이후의 초기 경로는 알고리즘별로 달라질 수 있다. 이 예제 결과만으로 성능 우열을 판단하지 않는다.

`waypoint_trace.py`는 실제 함수의 다음 상태를 읽는다.

- GRASP: 제한 후보 목록(RCL), 선택 경유지, A*로 연결한 초기 경로.
- Local·VND: 변경 전 경로와 검토 후보(5개마다 표본), 실제 개선 채택(모두), VND 이웃 번호.
- VNS: 교란 레벨과 교란 후 경로, 이후 VND 개선 기록.
- ALNS: 일부 제거·재삽입한 경유지 순서, 내부 수락 판단, 도로 재연결 후 조립 계층의 최종 채택·기각.
- 전체: 최선해 갱신, 최종 정리와 반환 결과. 계측 과정은 추가 A*나 난수를 호출하지 않는다.

보라색 점선은 경유지 순서를 설명하며 실제 도로가 아니다. 도로로 복원된 경로는 실선으로 표시한다. ALNS 내부 수락과 조립 계층의 최종 채택은 별도 단계다. VND의 AlternativeSegment 이웃은 기존 코드에서 비활성이라 시각화에서도 나타나지 않는다.

재생 화면은 어두운 배경과 밝은 탐색 연결선을 사용한다. 상황마다 전체 탐색 범위에 맞춰 화면을 잡으며 `＋`/`－`·마우스 휠로 확대하고 드래그로 이동할 수 있다. `전체보기`는 해당 상황의 범위로 복원한다. A*의 확인한 연결은 NetworkX의 실제 부모 관계이며, 확인한 노드 사이에 있는 모든 도로를 탐색했다고 칠하지 않는다.

관련 구조 설명은 [PR #399](https://github.com/ChimaekMeeting/seoul-walk-platform/pull/399), ALNS 통합 도식은 [PR #404](https://github.com/ChimaekMeeting/seoul-walk-platform/pull/404), VNS 설정·VND 비활성 이웃 설명은 [PR #408](https://github.com/ChimaekMeeting/seoul-walk-platform/pull/408)을 참고한다. 시각화의 코드 위치는 다음과 같다.

| 파일 | 책임 |
|---|---|
| `visualizations/routes.py` | 시나리오 실행·계측 전후 비교·산출물 저장 |
| `visualizations/route_experiment.py` | 엔진 실행 조건과 경로 검증 |
| `visualizations/route_trace.py` | A*·기존 Beam 기록 |
| `visualizations/waypoint_trace.py` | GRASP·Local·VND·VNS·ALNS 기록 |
| `visualizations/route_story.py` | 장면별 경로 지표·변경 전후 비교·핵심 장면 선택 |
| `visualizations/route_view.py` | 기록을 화면 데이터·PNG로 변환 |
| `visualizations/route_player.html` | 재생·단계 이동·확대·이동 화면 |

기본 명령으로 생성한 재생 화면에는 세 엔진만, `--with-grasp`로 생성한 화면에는 8개 실행 결과와 9개 요청 선택 항목이 들어간다(‘그냥 3km’는 순환과 같은 결과). 이미 생성한 HTML은 자체 데이터를 포함하므로 새 코드를 실행해 새로 생성해야 화면 변경이 반영된다.

## 결과 비교와 핵심 장면 읽기

새 화면은 순환 결과 비교표에서 시작한다. 현재 선택과 출발·복귀 조건 및 목표 거리가 같은 실행끼리 묶으며, 최단거리와 편도 우회는 각각 별도 결과 표로 표시한다. ‘그냥 3km’ 요청은 동일한 순환 결과를 재사용하므로 비교표에 중복 행을 만들지 않는다. 표의 과정 보기 버튼으로 해당 알고리즘을 선택한다.

- 비교표: 반환 첫 후보의 거리, 절대 목표 오차, 엔진별 허용 오차와 충족 여부, 재통행 비율, 실제 계산 시간. 재통행 비율은 이미 지난 무방향 엣지를 다시 걷는 거리의 합 / 전체 거리다. 경로 연결 실패와 목표 범위 밖을 구분한다.
- 시간: 기록을 끈 실행에서 `perf_counter()`로 `engine.run()` 직전부터 반환 직후까지 1회 측정한다. artifact 읽기, 그래프 깊은 복사, 엔진 생성, 계측 준비, 결과 검증과 그림 생성은 제외한다. `run()` 내부 전처리와 응답 생성은 포함한다. 반환 경로를 수집하는 얇은 prune 래퍼는 유지된다. 기록 실행 다음에 측정하므로 최초 실행 지연이나 반복 성능 벤치마크가 아니다. `run_seconds`는 기록 실행 자체에는 `None`, 저장 결과에는 무계측 실행의 초 단위 값을 사용한다.
- 핵심 장면: 사건 종류별 첫 장면과 마지막 상태, 실제 개선·전체 최선 갱신·전후 거리 변화, 수락·기각을 우선해 최대 26개를 고른다. A*는 도착점까지 직선거리가 처음 25/50/75% 줄어든 순간도 포함한다. 시간이나 단계 수를 균등 간격으로 나누지 않는다. 압축 때문에 모든 변화가 나타나는 것은 아니며, 전체 기록 번호와 생략 수를 표시한다.
- 전체 기록: 원래 기록을 그대로 재생한다. 다만 지역 개선의 후보 검토는 기존처럼 5개마다 표본이고 실제 개선은 모두 기록한다. ‘전체’가 모든 내부 함수 호출을 뜻하지 않는다.

장면 옆 수치는 실제 도보 엣지 길이로 다시 계산한다. 미완성 부분 경로에는 최종 목표 오차를 붙이지 않고, 도로로 연결하기 전의 경유지 점선에는 거리·재통행 수치를 만들지 않는다. 분홍색과 하늘색은 각각 이전 경로와 이 단계 결과 또는 검토 후보이며, 기각된 후보를 반환 경로로 해석하지 않는다.

`refinement_done`은 조립 계층이 호출한 같은 초기 후보의 개선 전후를 연결한다. 서로 다른 재시작의 첫 후보와 최종 승자를 임의로 묶지 않는다. `winner`는 이전 전체 최선과 새 전체 최선의 비교다. Local/VND 채택과 VNS 교란 후 판단은 실제 `RouteObjective` 비교값을 기록한다. 목표 범위 충족이 우선이며, 둘 다 범위 밖이면 거리 오차 → 재통행, 둘 다 안이면 재통행 → 거리 오차 순이다. 동률은 기존 경로를 유지한다.

ALNS 내부 수락은 평가값 변화와 온도에 따른 판단을 기록한다. 내부 최선과 현재 해는 별개이며 내부 수락이 최종 반영을 뜻하지 않는다. 도로 재연결 후에는 경유지 최소 간격, 연결 성공, RouteObjective 비교에 따라 반영하거나 유지한 이유를 따로 표시한다. 최종 정리 단계는 목표 오차 개선을 조건으로 실행되는 것이 아니므로, 정리 후 오차가 커져도 그대로 표시한다.

화면 변경과 기록 변경은 `visualizations/**` 및 이 실행 문서에 한정한다. 입력 도보망·기존 서비스 알고리즘·API 계약은 변경하지 않는다. 실패 복구는 출력 폴더의 `summary.json`과 `trace.json`에서 시작하며, 화면만 바꾸었어도 새 HTML을 생성해야 한다. DB나 Docker 기동은 필요 없다.

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
