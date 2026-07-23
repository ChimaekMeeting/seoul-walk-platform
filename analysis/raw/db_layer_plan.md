# 도보 네트워크 RAW 데이터 DB/Layer 분류 계획

이 문서는 `src/data/raw`에 들어온 RAW 파일들을 DB에 어떻게 넣을지, 어떤 것은 메인 길망으로 쓰고 어떤 것은 검증/보강/POI/보류로 둘지 정리한다.

## 1. 기본 원칙

외부 RAW를 바로 점수로 만들지 않는다.

먼저 아래 세 층으로 분리한다.

1. `raw_*`: 원본 도보 네트워크 속성 그대로 보존
2. `validation_*`: 외부 RAW와 공간적으로 맞는지 검증한 결과
3. `interpreted_*`: 서비스/분석에서 실제로 쓸 해석 속성

예를 들어 `터널`, `건물내` 같은 원본 컬럼은 이름만 보고 바로 의미를 확정하지 않는다.

```text
raw_is_tunnel
road_tunnel_raw_near
tunnel_match_status
interpreted_tunnel_type
```

처럼 원본과 해석을 분리한다.

## 2. 핵심 DB 테이블

### walk_nodes

도보 네트워크의 NODE 행.

주 용도는 횡단보도/육교 같은 지점형 보행 구조를 담는 것이다.

| column | meaning |
|---|---|
| walk_node_id | 원본 노드 ID |
| geometry | Point |
| sigungu_code | 시군구코드 |
| sigungu_name | 시군구명 |
| emd_code | 읍면동코드 |
| emd_name | 읍면동명 |
| raw_is_crosswalk_node | 원본 횡단보도 NODE 플래그 |
| raw_is_overpass_node | 원본 육교 NODE 플래그 |
| crosswalk_validation_status | 외부 횡단보도 RAW와 검증 결과 |
| overpass_validation_status | 외부 육교 RAW와 검증 결과 |

판정:

```text
횡단보도/육교는 LINK보다 NODE가 정답.
NODE 속성은 신뢰하고 메인으로 사용.
```

### walk_edges

도보 네트워크의 LINK 행. 실제 라우팅 edge의 본체다.

| column | meaning |
|---|---|
| walk_edge_id | 원본 링크 ID |
| start_node_id | 시작노드 ID |
| end_node_id | 종료노드 ID |
| geometry | LineString/MultiLineString |
| length_m | 링크 길이 |
| sigungu_code | 시군구코드 |
| sigungu_name | 시군구명 |
| emd_code | 읍면동코드 |
| emd_name | 읍면동명 |
| raw_is_elevated | 원본 고가도로 |
| raw_is_subway_network | 원본 지하철네트워크 |
| raw_is_bridge | 원본 교량 |
| raw_is_tunnel | 원본 터널 |
| raw_is_overpass_link | 원본 육교 LINK |
| raw_is_crosswalk_link | 원본 횡단보도 LINK |
| raw_is_park_green | 원본 공원,녹지 |
| raw_is_building_inside | 원본 건물내 |
| interpreted_is_indoor_or_station_connected | 지하도/역/실내 연결 성격 |
| interpreted_tunnel_type | 도로터널 보도/보행터널 후보 등 |
| park_context | 공원 내부/인접 여부 |

주의:

```text
건물내 = 회사 건물 내부 복도만 뜻한다고 보면 안 됨.
지하철역 연계 지하도 RAW와 많이 맞으므로,
역사 내부, 지하상가, 지하 연결통로, 실내/반실내 보행 연결을 포함하는 속성으로 해석.
```

### validation_results

검증 결과를 요약 저장하는 테이블.

| column | meaning |
|---|---|
| validation_id | 검증 ID |
| target_table | walk_nodes / walk_edges / external_layer |
| target_attr | crosswalk / overpass / tunnel / park_green / indoor 등 |
| source_dataset | 비교한 외부 RAW |
| geometry_method | node_near / line_near / line_polygon_intersects |
| distance_m | 거리 기준 |
| candidate_count | 검증 대상 수 |
| matched_count | 매칭 수 |
| matched_rate | 매칭률 |
| decision | 신뢰 / 보강 후보 / 보류 / 충돌 |
| memo | 해석 메모 |

### external_poi

점형 보강 후보.

| poi_type | source | use |
|---|---|---|
| bus_stop | 서울시 버스정류소 위치정보 | 대중교통 접근성 |
| subway_lift | 서울시 지하철 출입구 리프트 위치정보 | 교통약자 접근성 |
| subway_elevator | 서울시 지하철역 엘리베이터 위치정보 | 교통약자 접근성 |
| restroom | 서울시 공중화장실 위치정보 | 편의시설 접근성 |
| park_point | 전국도시공원정보표준데이터 / 서울시 주요 공원현황 | 보조 참고만 |
| tree_point | 서울시 공원 및 사유지수목 위치정보 | 녹지/수목 보조 참고 |
| school_zone | 전국어린이보호구역표준데이터 | 어린이/보행 안전 후보 |
| cctv | 서울시CCTV정보 | 안전/감시성 후보, 밀도 정규화 필요 |
| smart_streetlight | 전국스마트가로등표준데이터 | 야간 안전 후보, 지역 편중 주의 |
| shop | 소상공인 상가정보 | 장소감/활성도 후보, 개별 POI보다 밀도 집계 |

기본 컬럼:

| column | meaning |
|---|---|
| poi_id | POI ID |
| poi_type | 유형 |
| source_dataset | 원본 데이터셋 |
| name | 명칭 |
| geometry | Point |
| nearest_walk_edge_id | 가장 가까운 도보 edge |
| distance_to_walk_m | 도보 edge까지 거리 |
| use_status | approved_candidate / hold / reference_only |

POI 후보별 현재 상태:

| poi_type | use_status | note |
|---|---|---|
| bus_stop | approved_candidate | 도보 edge 근접률 높음. 대중교통 접근성으로 사용 |
| subway_lift | approved_candidate | 교통약자 접근성 강한 후보 |
| subway_elevator | approved_candidate | 교통약자 접근성 강한 후보 |
| restroom | approved_candidate | `서울시 공중화장실 위치정보` 좌표 사용 가능, 50m 기준 적합 |
| school_zone | approved_candidate | 서울 row 2,199, 좌표 결측 없음. safety/school_zone 후보 |
| cctv | candidate_needs_density_normalization | 서울 row 57,757, 좌표 결측 없음. 개별 점수보다 밀도/정규화 필요 |
| smart_streetlight | limited_candidate | 서울 row 357, 좌표 결측 없음. 관악구 등 특정 지역 편중 주의 |
| shop | density_candidate | 대용량 POI. edge에 개별 nearest join하지 말고 업종별 밀도 집계 |
| park_point | reference_only | 공원 polygon이 있으므로 보조 참고만 |
| tree_point | reference_only | 점형 수목 데이터이므로 녹지 검증의 주 근거 아님 |

상가정보는 `external_poi` 원본으로는 관리하되, 분석/점수에는 개별 POI가 아니라 집계 테이블을 사용한다.

```text
edge_poi_density
- walk_edge_id
- poi_type = shop
- radius_m = 50 / 100
- count_total
- count_food
- count_cafe
- count_convenience
- count_medical
- count_retail
```

### external_line_layers

선형 보강 후보.

| layer_type | source | use |
|---|---|---|
| underground_passage | 서울시 지하철역 연계 지하도 공간정보 | 건물내/실내 연결 검증 및 보강 |
| pedestrian_priority_road | 전국보행자우선도로표준데이터 | 보행 친화/safety 보강 후보 |
| tree_road | 전국가로수길정보표준데이터 | 일반 도로변 그늘/녹음/쾌적성 후보 |
| trail | 서울시 둘레길 선형 위치정보 | 산책/공식 코스 후보 |
| culture_trail | 서울시 문화길 선형 위치정보 | 산책/문화 테마 후보 |
| bike_road | 전국자전거도로표준데이터 | active mobility 후보, 러닝 확정 아님 |
| crosswalk_line | 서울시 대로변 횡단보도 위치정보 | NODE 검증 보조 |
| overpass_line | 서울시 육교 공간정보 | NODE 검증 보조 |
| road_tunnel_raw | 전국도로터널정보표준데이터 | 도로터널 보도 검증 후보 |

자동차전용도로는 이 테이블에 넣지 않는다. 현재 CSV는 좌표계가 확정되지 않았고, 자동차전용도로는 본질적으로 점 POI가 아니라 회피/차단용 선형 barrier 성격이다.

### external_barrier_layers

회피/차단 후보 레이어.

| barrier_type | source | use_status | use |
|---|---|---|---|
| car_only_road | 서울시 자동차 전용도로 위치정보 | excluded_until_geometry_resolved | POI 아님. CRS/선형 geometry 확보 전 1차 DB에서 사용 안 함 |

### external_polygons

면형 데이터.

| polygon_type | source | use |
|---|---|---|
| park_polygon | 서울시 생활권계획 시설(공원) 공간정보 | 공원/녹지 검증의 주 근거 |

현재는 이 polygon 하나를 공원 검증의 기준으로 사용한다.

```text
park_inside = distance_m 0
park_near_20m = 공원 경계/인접 보행로
park_near_50m = 넓은 공원 접근/인접 후보
```

## 3. 데이터셋별 DB 처리

| RAW 데이터 | geometry | DB 처리 | 최종 역할 |
|---|---:|---|---|
| 서울시 자치구별 도보 네트워크 공간정보 | NODE + LINK | `walk_nodes`, `walk_edges` | 기본 길망 |
| 서울시 대로변 횡단보도 위치정보 | LineString | `external_line_layers` | 횡단보도 NODE 검증 보조 |
| 서울시 육교 공간정보 | LineString | `external_line_layers` | 육교 NODE 검증 보조 |
| 국토교통부 전국도로터널정보표준데이터 | LineString from endpoints | `external_line_layers` | 도로터널 보도 검증 후보 |
| 서울시 생활권계획 시설(공원) 공간정보 SHP 세트 | Polygon | `external_polygons` | 공원/녹지 검증 주 근거 |
| 서울시 지하철역 연계 지하도 공간정보 | LineString | `external_line_layers` | 건물내/실내 연결 검증 및 보강 |
| 서울시 버스정류소 위치정보 | Point | `external_poi` | transit_access 후보 |
| 서울시 지하철 출입구 리프트 위치정보 | Point | `external_poi` | accessibility 후보 |
| 서울시 지하철역 엘리베이터 위치정보 | Point | `external_poi` | accessibility 후보 |
| 서울시 공중화장실 위치정보 | Point | `external_poi` | restroom amenity 후보 |
| 공중화장실정보_서울특별시 | Address only | reference/hold | 좌표 파일이 있으므로 보조 메타만 |
| 전국보행자우선도로표준데이터 | LineString from endpoints | `external_line_layers` | walkability/safety 후보 |
| 전국가로수길정보표준데이터 | LineString from endpoints | `external_line_layers` | shade/scenic 후보 |
| 전국도시공원정보표준데이터 | Point | `external_poi` | 공원 point 보조, 주 근거 아님 |
| 서울시 주요 공원현황 | Point/attribute | `external_poi` or reference | 공원 보조, polygon 우선 |
| 서울시 공원 및 사유지수목 위치정보 | Point | `external_poi` | 수목/녹지 보조 |
| 서울시 둘레길 선형 위치정보 WGS1984 | LineString | `external_line_layers` | 공식 산책 코스 후보 |
| 서울시 둘레길 점형 위치정보 WGS1984 | Point | reference | 선형 보조, 중복이면 우선순위 낮음 |
| 서울시 문화길 선형 위치정보 WGS1984 | LineString | `external_line_layers` | 문화 산책 후보 |
| ITRF2000 둘레길/문화길 파일 | Line/Point | hold | WGS1984가 있으므로 중복 보류 |
| 서울 둘레길.csv | Unknown/reference | hold | 기존 WGS1984 선형 우선 |
| 전국자전거도로표준데이터 | LineString from endpoints | `external_line_layers` | active mobility 후보, 러닝 확정 아님 |
| 서울시 자동차 전용도로 위치정보 | CRS unclear point | hold | 회피/차단 후보이나 CRS 확정 전 보류 |
| 서울시 하천.geojson | Line/Polygon | excluded_from_phase1 | 이번 1차 DB/score에서는 사용 안 함 |
| 전국스마트가로등표준데이터 | Point | `external_poi` | limited night_safety 후보, 특정 구 편중 주의 |
| 전국어린이보호구역표준데이터 | Point | `external_poi` | school_zone safety 후보 |
| 서울시CCTV정보 | Point | `external_poi` | safety 후보, 밀도 정규화 필요 |
| 소상공인 상가정보 | Point | `external_poi` + `edge_poi_density` | 장소감/활성도 후보, 업종별 밀도 집계로 사용 |

자동차전용도로와 하천의 현재 판정:

```text
자동차전용도로:
- POI로 쓰지 않음
- 현재 CSV X/Y는 WGS84/주요 EPSG 후보로 서울 bbox에 들어오지 않음
- CRS 또는 SHP/GeoJSON 선형 geometry 확보 전 1차 DB에서 제외

하천:
- 이번 분석에서 별도 검증하지 않음
- 공원/녹지/쾌적도 1차 근거는 서울시 생활권계획 시설(공원) polygon으로 충분
- 하천은 1차 DB/score에서 제외하고 후순위로 둠
```

## 4. 터널 처리 규칙

터널은 하나의 boolean으로 끝내지 않는다.

```text
raw_is_tunnel
road_tunnel_raw_near
road_tunnel_match_status
interpreted_tunnel_type
```

권장 값:

| case | meaning | action |
|---|---|---|
| raw_is_tunnel=True, road_tunnel_raw_near=True | 도보 터널과 도로터널 RAW가 가까움 | road_tunnel_sidewalk 가능성 높음 |
| raw_is_tunnel=True, road_tunnel_raw_near=False | 도보 네트워크에는 터널, 외부 RAW로는 설명 안 됨 | 원본 유지, geometry/정의 차이로 보류 |
| raw_is_tunnel=False, road_tunnel_raw_near=True | 외부 도로터널 근처 도보 edge인데 터널 플래그 없음 | possible_missing_road_tunnel_sidewalk, 자동 추가 금지 |
| raw_is_tunnel=False, no nearby walk edge | 외부 도로터널 주변 도보망 없음 | coverage/좌표/차도전용 가능성 확인 |

현재 결론:

```text
도보 네트워크의 터널 속성은 보행자가 통과 가능한 터널형 구간을 나타내며,
그 상당수는 도로터널 내부 또는 인접 보도일 가능성이 높다.
외부 도로터널 RAW는 도로시설물 중심선/입출구 기준이고,
도보 네트워크는 실제 보행 edge 기준이므로 공간 overlap이 낮게 나타날 수 있다.
```

## 5. 우선순위

1. `walk_nodes`, `walk_edges` 확정
2. NODE 기준 횡단보도/육교 확정
3. 공원 polygon 기준 `park_inside`, `park_near_20m`, `park_near_50m` 생성
4. 지하도 RAW로 `raw_is_building_inside` 해석 보강
5. 화장실/엘리베이터/리프트/버스정류소를 `external_poi`로 edge nearest 매핑
6. 보행자우선도로를 `external_line_layers`로 edge nearest 매핑
7. 터널은 subtype/validation status만 붙이고 자동 보강하지 않음
8. 가로수길/둘레길/문화길/자전거도로는 후순위 보강 후보
9. 어린이보호구역/CCTV/스마트가로등/상가정보는 `external_poi`로 정리하되, CCTV/상가정보는 밀도 집계로 사용
10. 자동차전용도로와 하천은 1차 DB/score에서 제외
