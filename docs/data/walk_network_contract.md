# V1 도보 네트워크 NODE·LINK 적재 계약

## 1. 목적과 범위

V1의 기준 그래프는 `서울시 자치구별 도보 네트워크 공간정보.csv` 하나로 생성한다.

코드·분포·품질 판단의 프로젝트 내 근거 문서는 `src/data/raw/metadata/서울시_도보네트워크_데이터정의서.md`이다.

- `NODE` 행은 `walk_nodes`의 기준 원본이다.
- `LINK` 행은 `walk_edges`의 기준 원본이다.
- 횡단보도·육교처럼 NODE와 LINK에 모두 존재하는 값은 둘 다 보존한다.
- 실제 경로 통행·차단 판단은 구간인 `walk_edges`의 속성과 태그를 사용한다.
- 다른 RAW 파일은 기준 그래프를 새로 만드는 자료가 아니라 속성 검증·보강 또는 스코어 산정 후보이다.

## 2. 원본 손실 방지와 현재 구현

`BaseNetworkCollector`는 NODE와 LINK 행을 분리해 읽는다. NODE 원본을 우선 적재하고, LINK가 참조하지만 NODE 행에 없는 끝점만 `derived_endpoint`로 보완한다.

현재 원본의 기준 건수는 다음과 같다.

| 항목 | 건수 |
|---|---:|
| 전체 행 | 491,082 |
| NODE 행 | 212,066 |
| LINK 행 | 279,016 |
| LINK가 참조하는 고유 노드 ID | 214,237 |
| LINK에는 있지만 NODE 행에는 없는 노드 ID | 2,175 |
| NODE 행에는 있지만 LINK가 참조하지 않는 노드 ID | 4 |

현재 구현은 다음 값을 보존한다.

- NODE의 원본 WKT, 유형 코드, 육교·횡단보도 플래그
- LINK의 유형 코드, 통행 주체 boolean, 형태 플래그와 WKT
- 보행 불가 LINK의 DB 원본과 `is_walkable=false`
- 원본 플래그에서 생성한 NetworkX Edge `tags`

시군구·읍면동과 수집일자는 현재 라우팅 Entity에 저장하지 않는다. 추적성이 필요하면 별도 provenance 계약으로 추가한다.

`GraphRepository`는 `tunnel`, `bridge`, `overpass`, `crosswalk`, `elevated`, `subway_network`, `park_green`, `building_inside` 태그를 생성한다. 다만 현재 모든 프로필이 차단하는 `underground` 태그는 생성하지 않으므로, 프로필과 실제 태그의 의미를 맞추는 후속 수정이 필요하다. 또한 `park_overlap_ratio`는 DB에 저장되지만 아직 NetworkX Edge에 전달되지 않는다.

## 3. V1 적재 원칙

### 3.1 원본 코드와 현재 조사에서 도출한 해석을 함께 저장한다

원본 코드와 플래그는 `raw_*` 필드로 보존한다. 동시에 현재 팀 조사 문서에서 도출한 NODE/LINK 코드 해석을 서비스에서 사용할 명시적 필드로 변환한다.

이 코드 해석은 현재 데이터 분포 및 비교 조사와 일치하지만, 이 문서 작성 시점에는 서울시 원천 데이터 사전이나 공식 명세로 교차 확인하지 않았다. 따라서 V1 구현 근거로 사용하되 공식 명세를 찾으면 반드시 다시 대조한다.

```text
원본 보존: raw_link_type_code = "1011"
확인된 해석:
- allows_pedestrian = true
- allows_vehicle = false
- allows_bicycle = true
- allows_pm = true
```

코드 자체를 보존하는 이유는 의미를 몰라서가 아니라, 추후 파싱 오류를 검증하고 원본과 파생 필드를 대조할 수 있게 하기 위해서다.

### 3.2 NODE는 지점, EDGE는 통행 구간이다

- NODE 속성: 교차점이나 특정 지점 자체의 특성
- EDGE 속성: 보행자가 실제로 지나가는 구간의 특성
- 경로 제외와 비용 계산: EDGE 기준

NODE의 횡단보도·육교 플래그를 보존하더라도, 해당 NODE 전체를 삭제하는 방식으로 통행을 막지 않는다. 연결된 각 EDGE의 통행 속성을 판단해야 한다.

### 3.3 DB에는 명시적 컬럼을 저장하고 태그는 한 곳에서 생성한다

DB에는 검색·검증이 쉬운 boolean 컬럼을 저장한다. `GraphRepository`가 이 컬럼으로 NetworkX edge의 `tags`를 생성한다.

```text
walk_edges.raw_is_tunnel = true
→ NetworkX edge.tags에 "tunnel" 추가
```

DB boolean과 별도의 JSON 태그를 함께 저장해 두 표현이 어긋나게 만들지 않는다.

## 4. WalkNode 매핑

| V1 필드 | 원본 컬럼 | 처리 기준 | 상태 |
|---|---|---|---|
| `node_id` | `노드 ID` | 정수 변환, PK | 필수 |
| `raw_node_type_code` | `노드 유형 코드` | 원본 코드 보존 | 필수 |
| `node_type` | `노드 유형 코드` | 아래 확인된 코드표에 따라 문자열로 변환 | 필수 |
| `raw_is_overpass` | `육교` | `1 → true`, `0 → false` | 필수 |
| `raw_is_crosswalk` | `횡단보도` | `1 → true`, `0 → false` | 필수 |
| `geom` | `노드 WKT` | SRID 4326 Point | 필수 |

V1 라우팅에 직접 필요하지 않은 시군구·읍면동·수집일자는 우선 적재 대상에서 제외한다. 추적성이 필요해지면 별도 provenance 필드로 추가한다.

현재 조사에서 도출한 NODE 코드표:

| 코드 | `node_type` | 의미 |
|---:|---|---|
| 0 | `general` | 일반노드 |
| 1 | `subway_entrance` | 지하철 출입구 |
| 2 | `bus_stop` | 버스정류장 |
| 3 | `visually_impaired_entrance` | 시각장애인 출입구 |

### NODE 행이 없는 링크 끝점

LINK가 참조하지만 NODE 행에는 없는 노드가 존재한다. 이런 노드는 LINK WKT의 시작점 또는 끝점으로 보완 생성한다.

```text
raw_node_type_code = null
node_type = "derived_endpoint"
raw_is_overpass = null
raw_is_crosswalk = null
geom = LINK WKT endpoint
```

`null`은 원본 NODE 행이 없어 플래그를 확인할 수 없다는 뜻이다. 알고리즘 호환용 기존 필드의 기본값은 `false`로 두되, 원본 플래그와 구분한다. 로그에 보완 노드 수를 반드시 남긴다.

## 5. WalkEdge 매핑

| V1 필드 | 원본 컬럼 | 처리 기준 | 상태 |
|---|---|---|---|
| `link_id` | `링크 ID` | 정수 변환, PK | 필수 |
| `start_node` | `시작노드 ID` | `walk_nodes.node_id` 참조 | 필수 |
| `end_node` | `종료노드 ID` | `walk_nodes.node_id` 참조 | 필수 |
| `raw_link_type_code` | `링크 유형 코드` | 앞자리 0도 보존하도록 4자리 문자열로 저장 | 필수 |
| `length_m` | `링크 길이` | 미터 단위 실수 | 필수 |
| `allows_pedestrian` | `링크 유형 코드` 첫 번째 자리 | `1 → true`, `0 → false` | 필수 |
| `allows_vehicle` | `링크 유형 코드` 두 번째 자리 | `1 → true`, `0 → false` | 필수 |
| `allows_bicycle` | `링크 유형 코드` 세 번째 자리 | `1 → true`, `0 → false` | 필수 |
| `allows_pm` | `링크 유형 코드` 네 번째 자리 | `1 → true`, `0 → false` | 필수 |
| `is_walkable` | `allows_pedestrian` | 보행 가능 여부를 나타내는 라우팅용 필드 | 필수 |
| `raw_is_elevated` | `고가도로` | `1 → true`, `0 → false` | 필수 |
| `raw_is_subway_network` | `지하철네트워크` | `1 → true`, `0 → false` | 필수 |
| `raw_is_bridge` | `교량` | `1 → true`, `0 → false` | 필수 |
| `raw_is_tunnel` | `터널` | `1 → true`, `0 → false` | 필수 |
| `raw_is_overpass` | `육교` | `1 → true`, `0 → false` | 필수 |
| `raw_is_crosswalk` | `횡단보도` | `1 → true`, `0 → false` | 필수 |
| `raw_is_park_green` | `공원,녹지` | `1 → true`, `0 → false` | 필수 |
| `raw_is_building_inside` | `건물내` | `1 → true`, `0 → false` | 필수 |
| `geom` | `링크 WKT` | SRID 4326 LineString | 필수 |
| 기존 score 필드 | 보조 데이터·Layer | 현행 점수 컬럼 유지 | 필수 |

현재 조사에서 도출한 LINK 코드 해석:

| 코드 | 통행 가능 주체 | 현재 건수 |
|---|---|---:|
| `1111` | 보행자·차량·자전거·PM | 236,575 |
| `1011` | 보행자·자전거·PM | 26,975 |
| `1000` | 보행자 | 15,131 |
| `1100` | 보행자·차량 | 49 |
| `1010` | 보행자·자전거 | 29 |
| `1110` | 보행자·차량·자전거 | 4 |
| `0101` | 차량·PM | 1 |
| `0011` | 자전거·PM | 6 |
| `0111` | 차량·자전거·PM | 38 |
| `0000` | 통행 불가 | 99 |
| `0100` | 차량 | 109 |

첫 번째 자리가 `0`인 253개 LINK는 보행 불가이다. DB에는 원본과 `is_walkable=false`를 보존하되, 실제 NetworkX 라우팅 그래프에서는 기본적으로 제외한다.

별도 자동차전용도로 같은 외부 자료는 이 253개를 검증하거나 원본에서 누락된 보행 불가 구간을 보강할 때 사용한다. 외부 데이터의 이름이나 단순 근접 여부만으로 추가 구간을 자동 차단하지 않는다.

## 6. NetworkX 속성과 태그 생성

`GraphRepository`는 모든 V1 edge 필드와 score를 NetworkX edge에 전달한다.

| DB 조건 | NetworkX tag |
|---|---|
| `is_walkable == false` | `not_walkable` — 기본 라우팅 그래프에서는 해당 edge 자체를 제외 |
| `raw_is_elevated == true` | `elevated` |
| `raw_is_subway_network == true` | `subway_network` |
| `raw_is_bridge == true` | `bridge` |
| `raw_is_tunnel == true` | `tunnel` |
| `raw_is_overpass == true` | `overpass` |
| `raw_is_crosswalk == true` | `crosswalk` |
| `raw_is_park_green == true` | `park_green` |
| `raw_is_building_inside == true` | `building_inside` |

태그 생성 함수는 전체 그래프 로드와 반경 그래프 로드가 공동으로 사용해야 한다.

```text
WalkEdge 명시적 속성
→ GraphRepository의 단일 tag 변환 함수
→ NetworkX edge.tags
→ graph filter / scoring / route algorithm
```

## 7. 보조 데이터의 역할

다른 RAW 파일은 아래 세 범주 중 하나로 분류한다.

| 범주 | 목적 | 예시 |
|---|---|---|
| `edge_attribute_candidate` | 통행 가능 여부나 edge 태그 검증·보강 | 자동차전용도로, 횡단보도, 육교, 터널, 지하도 |
| `score_source` | Layer를 거쳐 WalkEdge score 생성 | 가로등, CCTV, 공원, 가로수, 둘레길 |
| `poi_or_metadata_source` | WalkNode·WalkEdge 연결 시설 또는 설명 속성 | 화장실, 버스정류소, 엘리베이터, 리프트, 주요 공원 |
| `deferred_or_reference` | 품질 문제로 보류 또는 조사 전용 | 유효 Line이 없는 둘레길·문화길, 중구 한정 수목 |

각 파일은 다음 항목이 모두 결정되어야 적재 승인 상태가 된다. 25개 원본의 확정값은 [`dataset_roles.md`](dataset_roles.md)의 `11.6 최종 서비스 역할과 상태 확정`을 단일 기준으로 사용한다.

1. V1 사용 여부
2. 역할 범주
3. RAW 적재 위치
4. 생성할 Layer 또는 보강할 WalkEdge 필드
5. 반영할 score 또는 tag
6. 공간 매핑 방식과 검증 기준
7. 현재 코드 구현·실행 여부

## 8. 업무 경계와 구현 순서

### 데이터 작업

1. `WalkNode`, `WalkEdge` 엔티티에 V1 필드 추가
2. `BaseNetworkCollector`가 NODE 행을 우선 사용하도록 수정
3. 누락 NODE를 LINK endpoint로 보완
4. LINK 유형 코드를 통행 주체별 boolean으로 파싱
5. LINK 원본 플래그를 `WalkEdge`에 적재
6. 개발 검증은 `upsert`, 최종 스냅샷 검증은 `rebuild`로 실행
7. 보조 데이터의 V1 사용·적재·Layer·score 상태표 확정
8. 승인된 데이터의 Layer와 WalkEdge score 생성
9. 필요한 데이터만 최종 재적재하고 건수·결측·참조 무결성을 검증

데이터 작업은 알고리즘이 사용할 수 있는 DB 필드와 의미를 계약으로 전달하는 데까지 담당한다.

### 경로 알고리즘 연동

1. `GraphRepository`가 보행 불가 edge를 제외
2. DB 필드와 score를 NetworkX에 전달
3. 필터에 필요한 최소 속성만 `tags`로 변환
4. `blocked_tags`와 경로 알고리즘 동작 테스트

이 단계는 데이터 적재가 아니라 경로 알고리즘의 데이터 소비 단계이다.

### 챗봇 하네스 엔지니어링

`src/agents`의 챗봇 노드 입력·출력과 노드 간 연결 관계를 재정의한다. 보행 그래프의 `WalkNode`·`WalkEdge` 또는 NetworkX 태그 작업과는 별개이다.

## 9. 완료 조건

데이터 작업의 완료 조건:

- NODE와 LINK 원본 속성이 DB에서 유실되지 않는다.
- 보행 불가 LINK가 `is_walkable=false`로 식별된다.
- 보조 데이터마다 V1 사용 여부, 적재 위치, 생성 Layer와 반영 score가 문서화된다.
- 승인된 보조 데이터가 Layer와 WalkEdge score까지 실제로 연결된다.
- 빈 DB 재적재 결과와 기존 결과의 노드·엣지 건수 차이가 설명된다.
- 알고리즘 팀에 DB 필드의 의미와 소비 계약을 전달할 수 있다.

후속 경로 알고리즘 연동의 완료 조건:

- NetworkX edge에 통행 속성, score와 필요한 최소 `tags`가 전달된다.
- 차단 로직은 NODE 전체 삭제가 아니라 EDGE의 `is_walkable`과 필요한 필터 속성을 사용한다.
