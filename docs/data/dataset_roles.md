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

## 3. 상태값 분리

코드 연결과 V1 승인을 하나의 `active` 상태로 합치지 않는다.

| 구분 | 상태 | 의미 |
|---|---|---|
| 코드 | `wired` | RAW부터 Graph 또는 Layer·Score까지 실행 코드가 연결됨 |
| 코드 | `partial` | RAW 로더 등 일부 코드만 연결됨 |
| 코드 | `unwired` | 실행 코드에 연결되지 않음 |
| 검토 제안 | 사용 | 기존 분석상 V1 입력으로 사용할 수 있다고 판단 |
| 검토 제안 | 제한 사용 | 용도·지역·프로필을 제한해야 함 |
| 검토 제안 | 보류 | 품질·범위·정책 문제가 해결되기 전 사용하지 않음 |
| 검토 제안 | 참고 | 조사·검증 자료로만 사용 |
| 채원 승인 | `승인` | 채원이 V1 사용을 최종 결정함 |
| 채원 승인 | `미결정` | 채원이 아직 사용 여부를 결정하지 않음 |
| 제거 | `removed` | 중복 또는 V1 미사용으로 로컬 RAW에서 제거 |

현재 개발 DB에 실제 적재됐다는 뜻은 아니다. DB 상태는 `확인`, `미확인`, `미적재`로 별도 기록한다.

## 4. 기본 도보 그래프

| 데이터 | 역할 | 결과 | 코드 상태 | 채원 승인 | DB 상태 |
|---|---|---|---|---|---|
| 서울시 자치구별 도보 네트워크 공간정보 | V1 유일 기본 그래프 | `walk_nodes`, `walk_edges` | `wired` | `승인` | 미확인 |

V1에서는 다른 RAW의 Point나 LineString을 즉시 WalkNode·WalkEdge로 만들지 않는다. 기존 도보망에 없는 실제 보행 구간임이 확인되고 연결 지점까지 검증된 경우에만 그래프 보강 후보가 된다.

## 5. 현재 코드에 연결된 Layer·score

| 원본 | 역할 | Layer | WalkEdge 결과 | 코드 상태 | 채원 승인 | DB 상태 |
|---|---|---|---|---|---|---|
| OSM 녹지·공원·정원·초지 | Score Source | `nature_layer` | `nature_score` | `wired` | `미결정` | 미확인 |
| 스마트가로등·CCTV·사고다발지역 | Score Source | `safety_layer` | `safety_score` | `wired` | `미결정` | 미확인 |
| 어린이보호구역·어린이놀이시설 | Score Source | `child_layer` | `child_score` | `wired` | `미결정` | 미확인 |
| TourAPI 관광지·문화시설 | POI + Score Source | `landmark_layer` | `landmark_score` | `wired` | `미결정` | 미확인 |
| 공공데이터 실외운동기구 | POI + Score Source | `running_layer` | `running_score` | `wired` | `미결정` | 미확인 |

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
| ITRF2000 둘레길·문화길 파일 2개 | `removed` | WGS1984 선형 자료와 중복 |
| 둘레길 점형 위치정보 2개 | `removed` | 선형 자료가 우선 |
| 서울시 하천.geojson | `removed` | 현재 V1에서 미사용 |

## 10. 데이터별 완료 조건

각 데이터는 아래 항목이 모두 결정되어야 V1 데이터 작업이 완료된다.

1. V1에서 사용하는가
2. RAW 적재가 필요한가
3. POI·Line·Polygon·Score Source 중 무엇인가
4. 생성할 Layer가 무엇인가
5. 보강할 WalkEdge 필드 또는 score가 무엇인가
6. 공간 매핑과 품질 검증 기준이 무엇인가
7. 코드에서 실제로 실행되고 있는가
8. 개발 DB의 실제 적재 건수를 확인했는가

## 11. 기존 분석에서 직접 확인된 RAW 24개

이 표는 새로운 분석 결과가 아니라 기존 `analysis` 문서·노트북과 저장된 결과 CSV를 파일별로 연결한 것이다.

- `코드 상태`: 현재 코드가 RAW 적재부터 Layer·Score 또는 기본 그래프까지 연결되어 있는지를 표시한다.
- `검토 제안`: 기존 분석에서 확인한 품질·공간 범위·지역 편향을 바탕으로 한 데이터 담당자의 판단 초안이다.
- `채원 승인`: V1 실제 사용 여부의 최종 결정이다. 코드가 연결되어 있어도 자동으로 승인된 것은 아니다.
- `DB 상태=미확인`: 코드 연결 여부와 별개로 현재 개발 DB의 실제 행 수를 아직 조회하지 않았다는 뜻이다.

근거:

- `E1`: [`analysis/raw/walk_network_external_overlap_validation.ipynb`](../../analysis/raw/walk_network_external_overlap_validation.ipynb)
- `E2`: [`analysis/raw/db_layer_plan.md`](../../analysis/raw/db_layer_plan.md)
- `E3`: [`analysis/raw/raw_coverage_quality_dashboard.ipynb`](../../analysis/raw/raw_coverage_quality_dashboard.ipynb)
- `E4`: [`analysis/raw/raw_layer_mapping.ipynb`](../../analysis/raw/raw_layer_mapping.ipynb)
- `T`: `analysis/tables/raw`에 저장된 E1 실행 결과 CSV

| 번호 | RAW 데이터셋 | 기존 분석 결과 | 역할 | 코드 상태 | 검토 제안 | 채원 승인 | 현재 코드 연결 | 근거 | DB 상태 |
|---:|---|---|---|---|---|---|---|---|---|
| 1 | 서울시 자치구별 도보 네트워크 공간정보.csv | NODE 212,066·LINK 279,016. V1 기본 그래프이며 NODE/LINK 원본 필드 보존 필요 | 기본 그래프 | `wired` | V1 기본 그래프로 사용 | `승인` | `BaseNetworkCollector → walk_nodes/walk_edges` | E2, E3 | 미확인 |
| 2 | 서울시CCTV정보.xlsx | 서울 좌표 57,757행, 좌표 결측 없음. 24개 구가 식별되며 지역 편차가 큼 | 안전 Score Source | `wired` | 지역 편차 원인 확인 후 제한 사용 | `미결정` | `CSVSource → safety_layer → safety_score` | E2, E3, E4 | 미확인 |
| 3 | 전국스마트가로등표준데이터.csv | 서울 357행, 좌표 결측 없음. 식별된 구가 8개로 편중되어 보조지표로 제한 필요 | 안전 Score Source | `wired` | 서울 전체 Score 사용 보류 | `미결정` | `CSVSource → safety_layer → safety_score` | E2, E3, E4 | 미확인 |
| 4 | 전국어린이보호구역표준데이터.csv | 서울 2,199행, 좌표 결측 없음. 25개 구에 분포 | 어린이·안전 Score Source | `wired` | 어린이·가족 프로필용 사용 검토 | `미결정` | `CSVSource → child_layer → child_score` | E2, E3, E4 | 미확인 |
| 5 | 서울시 대로변 횡단보도 위치정보.csv | LINK 플래그와 20m 일치율은 낮지만 NODE 플래그는 양방향 약 99.6% 이상 일치. LINK 자동 보강 근거로 사용하지 않음 | NODE 플래그 검증 | `unwired` | NODE 플래그 검증용 사용 | `미결정` | 없음 | E1, E2, T | 미적재 |
| 6 | 서울시 육교 공간정보.csv | LINK 플래그와 일치율은 낮지만 NODE 플래그는 기존 NODE 기준 99.88%, RAW 기준 96.17% 일치 | NODE 플래그 검증 | `unwired` | NODE 플래그 검증용 사용 | `미결정` | 없음 | E1, E2, T | 미적재 |
| 7 | 국토교통부_전국도로터널정보표준데이터_20251231.csv | 서울 터널 254개, 보도폭이 있는 후보 97개. 기존 터널 LINK 검증은 가능하지만 자동 보강은 보류 | WalkEdge 터널 검증 | `unwired` | 기존 LINK 검증용 사용 | `미결정` | 없음 | E1, E2, T | 미적재 |
| 8 | 서울시 생활권계획 시설(공원) 공간정보 Shapefile | 4개 sidecar가 함께 있고 1,888개 Polygon/MultiPolygon이 정상 판독됨. 서울 bbox 100% | 공원 Polygon·자연 Score 후보 | `unwired` | 자연 Score 입력 후보 | `미결정` | 없음 | E2, T | 미적재 |
| 9 | 서울시 주요 공원현황.csv | 132개 대표점. 공원 내부 판정은 대표점보다 공원 polygon을 우선해야 함 | 공원 보조 Point | `partial` | 공원 명칭·속성 참고용 | `미결정` | `CSV raw` 등록, 러닝 전체 collector 비활성 | E1, E2 | 미확인 |
| 10 | 전국도시공원정보표준데이터.csv | 서울 bbox 내 3,871개 대표점. 50m 내 일반 도보망 근접률 44.23%, 녹지 LINK 근접률은 0.72%로 polygon 대체 불가 | 공원 보조 Point | `unwired` | 공간 판정에는 사용하지 않고 참고 | `미결정` | 없음 | E1, E2, T | 미적재 |
| 11 | 서울시 공원 및 사유지수목 위치정보 (좌표계_ WGS1984).csv | 2,203개 Point proxy. 공원·녹지 edge의 주 검증 근거로는 약함 | 수목·녹지 참고 Point | `unwired` | 자연 Score 주 입력으로 사용 보류 | `미결정` | 없음 | E1, E2 | 미적재 |
| 12 | 전국가로수길정보표준데이터.csv | 서울 후보 1,558개. 일반 도보망 50m 근접률 50.19%, 녹지 LINK 7.57% | 자연·그늘 Score 후보 | `partial` | 공간 범위 보완 전 Score 사용 보류 | `미결정` | `CSV raw` 등록, Layer collector 없음 | E1, E2, T | 미확인 |
| 13 | 서울시 둘레길 선형 위치정보 (좌표계_ WGS1984).csv | 2개 선형, 문화길과 합친 28개 선형 모두 서울 bbox 안. 전체 도보망 50m 근접률 89.29% | 공식 산책길 Line 후보 | `unwired` | 공식 산책길 후보로 검토 | `미결정` | 없음 | E1, E2, T | 미적재 |
| 14 | 서울시 문화길 선형 위치정보 (좌표계_ WGS1984).csv | 26개 선형. 둘레길과 함께 도보망 보강 후보이나 공원 polygon 검증 자료와는 분리해야 함 | 문화 산책길 Line 후보 | `unwired` | 문화 산책길 후보로 검토 | `미결정` | 없음 | E1, E2, T | 미적재 |
| 15 | 서울 둘레길.csv | 시작·종료 위치가 텍스트라 geocoding이 필요하고 WGS1984 선형 원본이 별도로 존재 | 중복·보조 코스 원본 | `partial` | WGS1984 선형 원본을 우선하고 보조자료로 보류 | `미결정` | `CSV raw` 등록, Layer 미연결 | E2 | 미확인 |
| 16 | 전국자전거도로표준데이터.csv | 서울 후보 188개 중 보행자 겸용 109개. 일반 도보망 50m 근접률 99.47%지만 러닝길로 바로 확정할 수 없음 | Active mobility Score 후보 | `partial` | 보행자 겸용 구간만 별도 검토 | `미결정` | `CSV raw` 등록, 러닝 전체 collector 비활성 | E1, E2, T | 미확인 |
| 17 | 전국보행자우선도로표준데이터.csv | 서울 후보 122개가 도보망 20m 안에 모두 근접 | 보행 친화 WalkEdge 보강 후보 | `unwired` | 보행 친화 속성 후보로 검토 | `미결정` | 없음 | E1, E2, T | 미적재 |
| 18 | 서울시 자동차 전용도로 위치정보 (좌표계_ GRS80).csv | 168개 행. 시험한 좌표계 후보가 모두 서울 bbox에 들어오지 않아 geometry·CRS 해결 전 사용 불가 | 보행 제한 검증 후보 | `unwired` | CRS 해결 전 사용 보류 | `미결정` | 없음 | E1, E2, T | 미적재 |
| 19 | 서울시 지하철역 연계 지하도 공간정보.csv | 3,072개 선형이 일반 도보망 50m 내 99.93%. `건물내` LINK와 50m 일치율 71.68%로 해석 보강 가능 | 실내·지하 연결 검증 | `unwired` | 실내·지하 LINK 검증 후보 | `미결정` | 없음 | E1, E2, T | 미적재 |
| 20 | 서울시 지하철 출입구 리프트 위치정보.csv | 83개 POI, 도보망 20m 근접률 98.80% | 접근성 POI | `unwired` | 접근성 프로필 후보 | `미결정` | 없음 | E1, E2, T | 미적재 |
| 21 | 서울시 지하철역 엘리베이터 위치정보.csv | 552개 POI, 도보망 20m 근접률 99.64% | 접근성 POI | `unwired` | 접근성 프로필 후보 | `미결정` | 없음 | E1, E2, T | 미적재 |
| 22 | 서울시 버스정류소 위치정보.csv | 11,253개 POI, 도보망 20m 근접률 99.48%. 도보 품질 점수보다는 교통 접근성 후보 | 접근성 POI | `partial` | 교통 접근성 용도로만 검토 | `미결정` | `CSV raw` 등록, Layer 없음 | E1, E2, T | 미확인 |
| 23 | 서울시 공중화장실 위치정보.csv | 4,415행 중 좌표 사용 가능 4,413개. 도보망 50m 근접률 95.97% | 편의시설 POI | `unwired` | 편의시설 표시·검색 후보 | `미결정` | 없음 | E1, E2, T | 미적재 |
| 24 | 공중화장실정보_서울특별시.csv | 좌표 컬럼이 없어 주소 geocoding이 필요. 좌표가 있는 서울시 공중화장실 파일을 공간 원본으로 우선 | 화장실 속성·보조 원본 | `partial` | 좌표 원본의 속성 보완용으로만 검토 | `미결정` | `CSV raw` 등록, Layer 없음 | E1, E2, T | 미확인 |

### 24개 기준 현재 요약

| 구분 | 상태 | 데이터셋 수 |
|---|---|---:|
| 코드 | `wired` | 4 |
| 코드 | `partial` | 6 |
| 코드 | `unwired` | 14 |
| 채원 승인 | `승인` | 1 |
| 채원 승인 | `미결정` | 23 |

현재 승인된 것은 V1 기본 그래프로 사용하는 서울시 도보 네트워크뿐이다. 나머지 23개는 기존 분석 근거와 위 제안을 보고 채원이 사용·보류·참고 여부를 결정한다.
