# V1 데이터 역할과 적재 상태

## 1. 명칭 원칙

`Node`와 `Edge`는 실제 도보 경로 그래프에만 사용한다.

```text
서울시 도보 네트워크 NODE → WalkNode
서울시 도보 네트워크 LINK → WalkEdge → NetworkX edge
```

지도상의 Point라고 해서 WalkNode가 되는 것은 아니다. 랜드마크·화장실·CCTV·버스정류장 등은 POI 또는 Layer의 Point로 관리한다.

| 명칭 | 의미 |
|---|---|
| `WalkNode` | 실제 도보망의 교차·분기·시작·종료 지점 |
| `WalkEdge` / `LINK` | 두 WalkNode를 연결하는 실제 보행 구간 |
| `POI` / Point Layer | 경로 주변 시설이나 장소 |
| Line Layer | 기존 WalkEdge의 속성 검증·보강에 사용하는 선형 자료 |
| Polygon Layer | 공원 등 영역 기반 점수·검증 자료 |
| Score Source | WalkEdge의 숫자 점수를 만드는 원본 또는 Layer |

## 2. 처리 단계

같은 “적재”라는 말로 네 단계를 섞지 않는다.

| 단계 | 의미 |
|---|---|
| RAW 적재 | 원본을 `*_raw` 테이블 또는 로컬 원본으로 보존 |
| Layer 변환 | 원본을 안전·자연·랜드마크 등 서비스 목적별 테이블로 정리 |
| Graph 반영 | 실제 WalkNode·WalkEdge 생성 또는 기존 WalkEdge 속성 보강 |
| Score 반영 | Layer를 `safety_score`, `nature_score` 등 WalkEdge 숫자 필드로 집계 |

## 3. 상태값

| 상태 | 의미 |
|---|---|
| `active` | V1 사용이 승인되고 실행 코드가 연결됨 |
| `candidate` | 목적은 정했지만 매핑·검증 또는 구현이 남음 |
| `deferred` | V1 사용 여부 또는 점수 정책 미확정 |
| `reference` | 조사·품질 검증용이며 서비스 DB에는 직접 반영하지 않음 |
| `removed` | V1 범위에서 제거 |

이 상태는 V1 정책과 코드 연결 상태를 뜻한다. 현재 개발 DB에 실제 적재됐다는 뜻은 아니다. DB 상태는 `확인`, `미확인`, `미적재`로 별도 기록한다.

## 4. 기본 도보 그래프

| 데이터 | 역할 | 결과 | 상태 | DB 상태 |
|---|---|---|---|---|
| 서울시 자치구별 도보 네트워크 공간정보 | V1 유일 기본 그래프 | `walk_nodes`, `walk_edges` | `active` | 미확인 |

V1에서는 다른 RAW의 Point나 LineString을 즉시 WalkNode·WalkEdge로 만들지 않는다. 기존 도보망에 없는 실제 보행 구간임이 확인되고 연결 지점까지 검증된 경우에만 그래프 보강 후보가 된다.

## 5. 현재 활성 Layer·score

| 원본 | 역할 | Layer | WalkEdge 결과 | 상태 | DB 상태 |
|---|---|---|---|---|---|
| OSM 녹지·공원·정원·초지 | Score Source | `nature_layer` | `nature_score` | `active` | 미확인 |
| 스마트가로등·CCTV·사고다발지역 | Score Source | `safety_layer` | `safety_score` | `active` | 미확인 |
| 어린이보호구역·어린이놀이시설 | Score Source | `child_layer` | `child_score` | `active` | 미확인 |
| TourAPI 관광지·문화시설 | POI + Score Source | `landmark_layer` | `landmark_score` | `active` | 미확인 |
| 공공데이터 실외운동기구 | POI + Score Source | `running_layer` | `running_score` | `active` | 미확인 |

랜드마크는 `landmark_layer`의 POI로만 저장한다. 고립된 랜드마크 WalkNode는 생성하지 않는다.

## 6. 기존 WalkEdge 속성 보강 후보

| 원본 | 예상 역할 | Graph 처리 | 상태 |
|---|---|---|---|
| 서울시 대로변 횡단보도 위치정보 | 횡단보도 플래그 검증 | 기존 WalkEdge의 원본 플래그와 비교 | `candidate` |
| 서울시 육교 공간정보 | 육교 플래그 검증 | 기존 WalkEdge의 원본 플래그와 비교 | `candidate` |
| 전국도로터널정보표준데이터 | 터널 플래그 검증 | 기존 WalkEdge의 터널 속성과 비교 | `candidate` |
| 서울시 자동차 전용도로 위치정보 | 보행 제한 검증 | 좌표계·선형 geometry 확인 후 `is_walkable` 검증 | `deferred` |
| 서울시 지하철역 연계 지하도 공간정보 | 실내·지하 연결 검증 | 기존 WalkEdge 포함 여부를 먼저 확인 | `candidate` |
| 전국보행자우선도로표준데이터 | 보행 친화 속성 후보 | 기존 WalkEdge에 공간 매핑 | `candidate` |

이 데이터들은 검증 전에는 새 WalkNode·WalkEdge를 만들지 않는다.

## 7. Score Source 후보

| 원본 | 예상 결과 | 상태 | 현재 주의점 |
|---|---|---|---|
| 서울시 생활권계획 시설(공원) 공간정보 | `nature_score` 보강 | `candidate` | Polygon 기준 공간 매핑 필요 |
| 전국가로수길정보표준데이터 | `nature_score` 보강 | `deferred` | collector 미구현 |
| 서울시 둘레길 선형 위치정보 | `running_score` 또는 산책 적합도 | `deferred` | V1 프로필 반영 정책 미확정 |
| 서울시 문화길 선형 위치정보 | 문화·랜드마크 점수 후보 | `deferred` | 반영 score 미확정 |
| 전국자전거도로표준데이터 | 활동성 점수 후보 | `deferred` | 러닝 적합성으로 바로 간주하지 않음 |
| 서울시 주요 공원현황 | 공원·러닝 보조 | `deferred` | Polygon 자료 우선 |

## 8. POI·표시 또는 향후 접근성 후보

| 원본 | 역할 | WalkNode 생성 | 상태 |
|---|---|---:|---|
| 서울시 지하철 출입구 리프트 위치정보 | 접근성 POI | X | `deferred` |
| 서울시 지하철역 엘리베이터 위치정보 | 접근성 POI | X | `deferred` |
| 서울시 공중화장실 위치정보 | 편의시설 POI | X | `deferred` |
| 서울시 버스정류소 위치정보 | 교통 접근성 POI | X | `deferred` |
| 소상공인 상가정보 | 상권 밀도 Score Source 또는 표시 POI | X | `deferred` |
| 서울시 공원 및 사유지수목 위치정보 | 녹지 검증 보조 Point | X | `reference` |

POI를 목적지와 연결해야 하면 POI 자체를 WalkNode로 만들지 않고, 가장 가까운 기존 WalkNode 또는 WalkEdge를 참조한다.

## 9. 보류·제거

| 원본 | 상태 | 이유 |
|---|---|---|
| ITRF2000 둘레길·문화길 파일 | `reference` | WGS1984 자료와 중복 |
| 둘레길 점형 위치정보 | `reference` | 선형 자료가 우선 |
| 서울시 하천.geojson | `removed` | 현재 V1에서 미사용 |

## 10. 데이터별 완료 조건

각 데이터는 아래 항목이 모두 결정되어야 `active`가 된다.

1. V1에서 사용하는가
2. RAW 적재가 필요한가
3. POI·Line·Polygon·Score Source 중 무엇인가
4. 생성할 Layer가 무엇인가
5. 보강할 WalkEdge 필드 또는 score가 무엇인가
6. 공간 매핑과 품질 검증 기준이 무엇인가
7. 코드에서 실제로 실행되고 있는가
8. 개발 DB의 실제 적재 건수를 확인했는가
