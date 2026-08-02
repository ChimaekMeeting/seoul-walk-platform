# GPS 아트 산책 경로 제안

> 상태: Proposal
> 기준일: 2026-08-02
> 기준 문서: [챗봇 Agent 하네스](../chatbot/agent_harness.md), [경로 생성 엔진](../route_engine/README.md), [챗봇 경로 추천 Workflow](../architecture/workflows/prewalk_conversation.md)
> 대상 코드: `src/agent/`, `src/agent/tools/gps_art_templates.py`, `src/route_engine/engines/`, `src/service/route/route_service.py`, `src/interfaces/schema/walk_schema.py`, `src/schema/prewalk_schema.py`, `src/prompt/extraction.yaml`

## 1. 목적과 범위

사용자가 "강아지런 할래"처럼 도형을 언급하며 산책을 요청하면, 미리 준비된 도형 템플릿(v1은 "강아지" 1개)의 순서 있는 좌표열을 조회해 실제 위경도로 변환한 뒤 도보망 노드에 매핑해 순환 경로로 잇는 기능("GPS 아트")을 제안한다.

이 문서는 대화로 정리된 설계 방향을 기록하고, 구현 전에 승인할 결정과 독립 작업 단위를 나눈다. 현재 챗봇·경로 흐름의 기준은 `agent_harness.md`와 `prewalk_conversation.md`를 따른다.

범위:

- Extractor의 도형 이름 추출 tool 추가
- 도형 템플릿 라이브러리(코드 상수) 관리
- 좌표 변환(오프셋 → 위경도)과 도보망 노드 매핑·유효성 처리
- 다중 waypoint를 순서대로 잇는 신규 경로 엔진
- `RouteService`/`RouteTool`/`RouteExecutor`에 신규 모드 연결

제외:

- `frontend/**` (확인 질문 문구 외 API 응답 schema 변경 없이 진행)
- 기존 circular/oneway 엔진 알고리즘 재설계
- 이 문서만으로 승인되지 않은 코드 변경

## 2. 현재 코드에서 확인된 사실

| ID | 현재 사실 |
|---|---|
| F1 | `Extractor`(`src/agent/nodes/extractor.py`)는 `ModeTool`(`src/agent/tools/mode_tools.py`)을 `bind_tools`로 연결해 LLM tool_call 하나로 모드와 구조화된 필드를 추출한다. 현재 도구는 `select_circular`/`select_oneway`/`select_oneway_shortest` 세 가지뿐이다. |
| F2 | `extraction.yaml`(`src/prompt/extraction.yaml`)은 장소명(`place_name`)만 추출하도록 지시하며, 좌표(lat/lon) 자체를 LLM이 생성하게 하는 규칙은 없다. |
| F3 | `WalkMode`(`src/interfaces/schema/walk_schema.py`)는 `circular_random`/`oneway_shortest`/`oneway_random` 세 값만 있고, `RouteService.base_engines`(`src/service/route/route_service.py`)도 이 세 모드만 엔진 클래스에 매핑한다. |
| F4 | `RouteService.get_route`는 origin/destination 단일 좌표쌍만 받는다. 순서 있는 다중 waypoint를 위한 입력 형태가 없다. |
| F5 | `PathUtils`(`src/route_engine/engines/path_utils.py`)에 이미 재사용 가능한 도구가 있다: `find_nearest_node_with_expansion`(R1=30m→R2=300m 2단계 최근접 노드 탐색), `connect_to`(경로 끝→목표 노드 최단 연결, 기방문 노드 재사용 시 패널티 부여 — 현재 순환 복귀·편도 도착 연결에 사용 중), `_NETWORK_FACTOR = 1.4`(직선거리→도로망거리 추정 계수, 서울 도심 블록 구조 기준), `_TOLERANCE_RATIO = 0.1`(기존 목표 거리 허용 오차 ±10%). |
| F6 | `Coordinate`(`walk_schema.py`)는 `validate_seoul_bounding_box`를 필수로 통과해야 생성된다. 변환된 좌표가 서울 경계를 벗어나면 이후 요청 자체가 거부된다. |
| F7 | `walk_nodes` 최근접 이웃 거리 실측(2026-08-02, 전체 214,894행 중 무작위 3,000행 샘플, PostGIS `ST_Distance(geography)` 기준): 중앙값 **16.0m**, p75 24.1m, p90 33.4m. `walk_edges`(전체 279,016행 중 3,000행 샘플)는 길이 중앙값 32.65m이며 76%가 시작·끝 노드만 있는 2점 직선(geom `LINESTRING`)이다. 재현: PostgreSQL에 연결해 `TABLESAMPLE SYSTEM`으로 샘플링 후 KNN(`<->`)으로 최근접 이웃 조회. Pruning 전 전체 기준이며 실제 서비스 그래프(160,188개, 최대 연결요소)는 약간 더 성길 수 있다. |

## 3. 대화에서 정리된 설계 결정

| 결정 | 내용 | 상태 |
|---|---|---|
| D1 좌표 생성 주체 | 도형별 (x, y) 정수 좌표열은 LLM이 생성하지 않고, 미리 사람이 설계한 템플릿(`src/agent/tools/gps_art_templates.py`)에서 `shape` 이름으로 조회한다. LLM은 `select_gps_art` tool_call에서 `shape`·`target_km`만 추출한다. | 승인(수정) |
| D2 좌표 원점 | (0, 0)은 사용자가 설정한 출발지 위치이고, 나머지 점은 이 origin 기준 상대 오프셋이다. | 승인 |
| D3 좌표 개수 | 템플릿은 저작 시점에 상한선 개념으로 고해상도로 만든다(정확한 개수를 강제하지 않음, 목표 90~100개 내외). 실제 사용되는 점 개수는 고정하지 않고, 요청 시점 `target_km`에 맞춰 D7에서 다운샘플링해 매번 다시 계산한다. 현재 `gps_art_templates.py`의 "강아지"는 25개(수작업, 다리4·몸통·머리)로 저해상도 상태이며 고해상도 재작성이 필요하다(P3 선행 조건). | 승인(수정) |
| D4 노드 매핑 검증 | 별도 폴리곤·수계 검증 로직을 새로 만들지 않고, 기존 `find_nearest_node_with_expansion` 결과(스냅된 노드)와 원본 변환 좌표 간 거리가 **150m**를 넘으면 스냅된 노드 위치를 그대로 사용한다. | 승인 |
| D5 경로 종료 방식 | 항상 출발지로 복귀하는 순환 경로. | 승인 |
| D6 거리 허용 오차 | 기존 순환/편도의 `_TOLERANCE_RATIO`(±10%) 대신 **±20%**를 적용한다(형태 인식 가능성이 거리 정확도보다 우선). | 승인 |
| D7 (x, y) 단위 환산 | 2단계로 계산한다. **(1) 사용 점 개수 역산**: 목표 점 간격 상수 `TARGET_NODE_SPACING_M = 20`(F7 실측 — 중앙값 16m와 p75 24m 사이)을 기준으로 `n_used = clamp(round(target_km * 1000 / (TARGET_NODE_SPACING_M * _NETWORK_FACTOR(1.4))), 최소 8, len(템플릿))`을 구한다. **(2) 다운샘플링·환산**: 템플릿 좌표열을 `n_used`개로 균등 다운샘플링(인덱스 기준)한 뒤, 오프셋 1당 실제 거리(m) = `(target_km * 1000) / n_used / _NETWORK_FACTOR(1.4)`로 계산한다. 템플릿의 원래 점 개수(`len(points)`)를 그대로 쓰지 않고, target_km마다 다시 계산된 `n_used`를 쓴다. | 승인(수정) |
| D8 프론트엔드·확인 흐름 | 이번 범위에서 FE는 변경하지 않는다. 확인 질문은 기존 패턴을 유지하고 문구만 "이 모양으로 만들까요?"로 분기한다. | 승인 |
| D9 Agent 통합 방식 | 신규 LangGraph Node·Edge와 State 필드를 추가하지 않는다. 기존 세 모드처럼 `ModeTool`의 tool 하나로 Extractor에 통합하고, `user_context`의 기존 Union 타입에 신규 Preference를 추가하는 방식으로만 확장한다. 템플릿 조회·좌표 변환·노드 매핑(P3)도 LLM 판단이 아닌 결정적 연산이므로 별도 Node 없이 `RouteTool`의 신규 함수 내부 로직으로 둔다. | 승인 |
| D10 도형 목록 관리 | D1 변경(템플릿 방식 채택)에 따라 도형 목록을 코드에 고정 라이브러리로 관리한다(`gps_art_templates.py`의 `GPS_ART_TEMPLATES` dict). v1은 "강아지" 1개만 등록하고, 다른 도형은 검증된 템플릿을 추가로 등록하는 방식으로 확장한다. `shape`는 자유 문자열이 아니라 템플릿에 등록된 이름만 허용한다. 경로 생성 결과는 기존과 동일하게 `route_histories`에 저장한다(변경 없음). | 승인(D1 변경에 따라 수정) |

D1~D10 모두 승인되었다(D1·D3·D7·D10은 아래 이력에 따라 수정).

D9의 근거: `chatbot_upgrade_proposal.md`의 C1(선언된 Graph Edge가 실제로는 도달하지 않는 문제)이 이미 지적되어 있다. 신규 Node·Edge를 추가로 선언하면 같은 문제가 반복될 위험이 있어, 기존 tool 확장 패턴을 그대로 따르는 쪽이 더 안전하다고 판단했다.

D1 변경 이력: 최초 결정은 LLM이 좌표를 자유 생성하는 방식이었다. 실제 tool_call 결과를 4회 반복 확인한 결과 (1) 닫힘·범위 제한 등 구조적 제약은 프롬프트 지시를 잘 따랐지만, (2) 도형 인식 가능성은 few-shot 예시를 추가한 뒤에도 개선되지 않았고(원점을 두 번 지나는 이중 루프, 반복 구간 재발 등), 오히려 개수(D3)까지 지시를 벗어났다. 이에 따라 좌표 생성 주체를 LLM에서 고정 템플릿으로 전환했다(D1). D10(도형 라이브러리 미보유)은 템플릿 전환과 동시에 다시 뒤집혔다.

D3·D7 변경 이력: 템플릿 전환 직후에는 "점 개수를 고정하지 않고 `len(points)`를 그대로 쓴다"로 정했으나, 도보망 노드 간격을 가정치(30m)가 아니라 F7로 실측해보니 target_km이 짧을 때(예: 1km) 고정된 템플릿 점 개수가 실제 노드 간격보다 훨씬 촘촘해져 인접 점 대부분이 같은 노드로 뭉개지는 문제가 확인됐다. 점 개수를 하나의 절충값(예: 45개)으로 고정하는 대신, 템플릿은 고해상도 상한으로 두고 target_km마다 적정 점 개수를 역산해 다운샘플링하는 현재 방식으로 다시 수정했다.

## 4. 독립 작업 단위

### P1. Mode·Schema 확장

- 책임: `WalkMode`에 신규 모드값 추가, 관련 `WalkRouteStatus` 실패 상태 정의, 순서 있는 다중 waypoint를 담는 입력 스키마 정의.
- 입력: `walk_schema.py`, 승인된 D1~D3
- 출력: 신규 `WalkMode` 값, waypoint 리스트 스키마, 관련 `WalkRouteStatus` 값
- 의존성: 없음
- 변경 영향: `RouteService`, `RouteTool`, `RouteExecutor`, `prewalk_schema.py`처럼 `walk_schema.py`를 참조하는 모든 코드
- 실패 복구: enum·스키마 추가만으로는 기존 세 모드 동작에 영향 없음 — 추가한 값만 제거하면 원복
- 완료 기준: 기존 세 모드의 기존 테스트가 그대로 통과하고, 신규 값이 validation을 통과한다.

### P2. Extractor Tool 추가

- 책임: LLM이 도형 이름(현재는 "강아지" 고정)·target_km만 tool_call로 추출하도록 `ModeTool`/`extraction.yaml` 확장. 좌표는 LLM이 생성하지 않는다.
- 입력: 승인된 D1·D10, `mode_tools.py`, `extraction.yaml`, `gps_art_templates.py`
- 출력: 신규 tool(도형 이름, target_km을 인자로 받음), `shape`는 템플릿에 등록된 이름만 선택하도록 명시한 프롬프트 규칙, `prewalk_schema.py`의 `user_context` Union에 신규 Preference 추가
- 의존성: P1
- 변경 영향: `Extractor.mode_tool.tool_map`(신규 tool은 독립 등록이라 기존 세 tool과 충돌 없음)
- 실패 복구: 신규 tool 등록을 커밋 단위로 되돌리면 기존 세 모드 추출에 영향 없음
- 완료 기준: "강아지" 도형을 언급하는 발화(fixture)에서 신규 tool이 `shape="강아지"`를 정확히 반환하고, 지원하지 않는 도형 언급 시 이 tool을 선택하지 않는다.

### P3. 템플릿 조회·다운샘플링·좌표 변환·노드 매핑

- 책임: `shape` 이름으로 `GPS_ART_TEMPLATES`에서 좌표열을 조회하고(템플릿에 없는 이름이면 실패 상태 반환), D7 공식으로 `target_km`에 맞는 `n_used`를 역산해 템플릿을 균등 다운샘플링하며, (0, 0) 기준 오프셋 좌표를 사용자 origin 기준 실제 위경도로 변환하고, 각 점을 `find_nearest_node_with_expansion`으로 노드에 매핑하고, 원본-스냅 거리가 D4 임계값을 넘는 점은 스냅된 노드 좌표로 대체한다.
- 입력: 승인된 D2·D4(수치)·D7(`TARGET_NODE_SPACING_M`, 다운샘플링 공식), 사용자 origin, P2 결과의 `shape`·`target_km`, `gps_art_templates.py`
- 출력: 템플릿 조회 함수, `n_used` 역산·다운샘플링 함수, 오프셋→위경도 변환 함수, 노드 매핑·임계값 대체 함수(`path_utils.py` 확장 또는 신규 유틸)
- 의존성: P1, P2
- 변경 영향: `path_utils.py`(기존 함수는 유지, 추가만 함), 신규 입력 스키마
- 실패 복구: 변환·매핑·다운샘플링 함수는 독립 단위 테스트 대상 — 실패 시 해당 함수만 롤백
- 완료 기준: 등록되지 않은 `shape` 요청 시 명시적 실패로 처리되고, 서울 경계를 벗어나는 오프셋이 입력돼도 `validate_seoul_bounding_box` 실패로 요청 전체가 거부되지 않으며(대체 로직 동작), target_km이 짧아도(예: 1km) 다운샘플링된 점 대부분이 서로 다른 노드에 매핑된다.

### P4. GPS 아트 경로 엔진

- 책임: 매핑된 노드들을 순서대로 잇고 마지막에 출발지로 복귀하는 신규 엔진 구현.
- 입력: 승인된 D5, P3 결과(순서 있는 노드열), 기존 `connect_to`
- 출력: `src/route_engine/engines/` 하위 신규 엔진 모듈, `connect_to`를 순서대로 반복 호출해 세그먼트를 잇는 구현
- 의존성: P3
- 변경 영향: `route_engine/engines/__init__.py` export 목록
- 실패 복구: 세그먼트 연결 실패(`connect_to`가 `None` 반환) 시 부분 경로를 성공으로 반환하지 않고 명시적 실패 `WalkRouteStatus`로 반환
- 완료 기준: 인접한 두 점이 동일 노드로 중복 스냅돼도 0-length 구간이 최종 경로에 남지 않고, 연결 실패는 실패 상태로 구분된다.

### P5. RouteService·RouteTool·RouteExecutor 연결

- 책임: 신규 모드를 기존 실행 파이프라인(`RouteService.get_route` → `RouteTool` → `RouteExecutor`)에 연결한다.
- 입력: P1·P4, 승인된 D6(거리 허용 오차)
- 출력: `RouteService.base_engines`에 신규 모드 매핑 추가, `RouteTool`에 신규 함수 추가, `RouteExecutor.MODE_TOOL_MAP`에 항목 추가
- 의존성: P1, P4
- 변경 영향: `get_route` 시그니처(현재는 origin/destination 단일 쌍만 받으므로 다중 waypoint 입력을 받도록 확장 필요)
- 실패 복구: 기존 세 모드 경로는 시그니처 변경 전후로 동일하게 동작해야 하며, 회귀 테스트 통과 후 병합
- 완료 기준: 도형 언급 발화가 신규 tool → 신규 route 함수 → `WalkRouteResponse`까지 end-to-end로 성공한다.

### P6. 확인 흐름 문구 반영 (FE 미변경)

- 책임: 기존 확인 질문 패턴을 유지한 채 신규 모드일 때 문구만 "이 모양으로 만들까요?"로 분기.
- 입력: 승인된 D8, 기존 Interviewer 확인 로직
- 출력: 확인 문구 조건 분기(신규 State·응답 필드 추가 없음)
- 의존성: P2
- 변경 영향: Interviewer 프롬프트/조건뿐이며 API 응답 schema는 변경하지 않음
- 실패 복구: 문구 조건만 되돌리면 기존 확인 흐름이 그대로 복원됨
- 완료 기준: 신규 모드로 확인 대기 상태에 진입했을 때 응답 schema가 기존 API 계약과 동일하다.

## 5. 권장 연결 순서

```text
P1 Mode·Schema 확장
├─ P2 Extractor Tool 추가 ── P6 확인 흐름 문구 반영
└─ (P2 완료 후) P3 좌표 변환·노드 매핑
      ↓
   P4 GPS 아트 경로 엔진
      ↓
   P5 RouteService·RouteTool·RouteExecutor 연결
```

P6은 P2 이후 별도 브랜치로 병렬 진행할 수 있다. P3~P5는 순서대로 의존한다.

## 6. 공통 검증 게이트

각 작업은 다음 증거를 남긴다.

1. `n_used` 역산·다운샘플링, 좌표 변환·임계값 대체 로직의 단위 테스트(경계 안/밖, 중복 스냅 케이스, target_km별 점 개수 변화)
2. 신규 엔진의 세그먼트 연결 성공·실패 단위 테스트
3. Extractor tool의 fixture 기반 `shape` 추출 검증(지원 도형/미지원 도형 케이스)
4. intent API를 통한 end-to-end 흐름(모드 선택 → 확인 → 경로 성공) 테스트
5. `route_histories`(PostgreSQL) 저장과 `nearby_pois` 조회 확인
6. 기존 세 모드의 회귀 테스트 통과 여부(신규 모드 추가가 기존 흐름을 깨지 않는지)

## 7. Proposal 승인과 완료 기준

구현 시작 전:

- 신규 모드·tool 이름을 확정한다.
- v1 이후 추가할 도형(고양이·하트·엄지 등) 템플릿의 우선순위와 제작 담당자를 정한다(D10).
- 각 작업(P1~P6)의 담당자와 선행 의존성을 정한다.

구현 완료:

- `agent_harness.md`, `route_engine/README.md`, `prewalk_conversation.md`(또는 신규 workflow 문서)를 새 코드와 대조해 갱신한다.
- 기존 세 모드의 정상·실패 흐름이 회귀 없이 유지됨을 확인한다.
- 승인되지 않은 Proposal 문장을 Current 문서에 남기지 않는다.
