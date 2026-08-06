# 경로 생성 엔진

> 상태: Current
> 기준일: 2026-08-06
> 관련 코드: `src/route_engine/`

경로 생성 엔진은 외부 API나 챗봇 처리와 분리된 경로 계산 영역입니다.

## 현재 구조

| 구성요소 | 위치 | 역할 |
|---|---|---|
| Graph | `src/route_engine/graph/` | DB 도보망을 NetworkX Graph로 준비·필터·직렬화 |
| Profile | `src/route_engine/profiles.py` | 사용자 선호 가중치와 차단 tags 정의 |
| Scoring | `src/route_engine/scoring/` | WalkEdge 속성과 Profile을 경로 비용으로 계산 |
| Engine | `src/route_engine/engines/` | 순환·편도 경로 탐색 알고리즘 |

## 계약 문서

- [경로 그래프 계약](graph_contract.md)

## Engine 반환 계약

- `circular_beam`(`CircularBeamEngine`)·`oneway_beam`(`OnewayBeamEngine`)·`oneway_astar`(`OnewayAstarEngine`) 3개 엔진의 `run()`은 `List[WalkRouteResponse]`를 반환한다.
- 같은 엔진들의 `find_path()`도 노드ID 경로 후보를 `list[list[int]]`로 감싸서 반환한다.
- 현재는 항상 경로 1개만 생성해 리스트에 담아 반환한다. 여러 경로 후보를 동시에 생성하는 기능은 아직 구현하지 않았다.
- `oneway_shortest` 모드의 실제 사용 엔진은 `dijkstra.py`(`OnewayDijkstraEngine`)에서 `oneway_astar.py`(`OnewayAstarEngine`)로 교체되었다. `OnewayDijkstraEngine`은 여전히 존재하지만 `route_service.py`에서는 더 이상 쓰지 않는다(벤치마크 등 다른 용도로만 남아있는지는 별도 확인 필요).
- `route_service.get_route()`도 같은 계약(`List[WalkRouteResponse]`)으로 반환하며, 리스트의 첫 번째 요소만 사용해 POI 조회·이력 저장을 수행하고 리스트 전체를 그대로 반환한다.

## Waypoint(경유지) 조합 엔진

- `waypoint.py`(`WaypointComposerEngine`)는 출발지 → 경유지들 → 목적지를 구간(leg)별로 나눠, 각 leg에 지정된 모드의 기존 편도 엔진(`OnewayAstarEngine`/`OnewayBeamEngine`)을 순차 호출해 하나의 경로로 이어 붙인다. 새 탐색 알고리즘은 추가하지 않고 기존 엔진을 조합만 한다.
- 입력은 `WaypointRouteInput`(`src/schema/route_schema.py`)이며 `waypoints`(경유지 좌표 리스트), `leg_modes`(leg별 모드), `leg_target_km`(leg별 목표 거리, `oneway_random` leg만 필수)로 구성된다. `len(leg_modes) == len(waypoints) + 1`이어야 한다.
- `leg_modes`/`leg_target_km`은 `WalkMode`/`Coordinate`를 그대로 쓰지 않고 `route_schema.py` 안에 로컬로 정의한 `WaypointLegMode`(`Literal["oneway_shortest", "oneway_random"]`)와 `WaypointCoordinate`를 쓴다. `route_schema.py -> walk_schema.py -> route_engine.profiles -> route_schema.py(Weights)`로 이어지는 기존 순환 임포트 때문에 `walk_schema.py`의 타입을 직접 가져올 수 없어서다.
- `WaypointComposerEngine`은 그래프를 직접 mutate하지 않고 leg 엔진에 그대로 넘기기만 하므로 `G.copy()`를 하지 않는다(`self.G = G`). 실제 mutation(예: `OnewayBeamEngine`의 `custom_score` 계산)은 그걸 하는 leg 엔진이 자체적으로 격리한다. 인접 leg의 경계 좌표는 동일한 `(lat, lon)` 값을 그대로 재사용해 노드 스냅 불일치를 방지한다.
- leg가 실패하면(그리고 아직 `oneway_shortest`로 시도하지 않았다면) `OnewayAstarEngine`으로 그 leg만 재시도한다(다른 엔진들의 `base_shortest` 대체와 같은 패턴). 그 재시도까지 실패해야 해당 leg에서 중단한다.
- 결과 상태(`_stitch`)는 모든 leg 성공 시 `SUCCESS`, 일부만 성공 시 `PARTIAL_ROUTE`(성공한 구간까지만 좌표·거리 반환), 첫 leg부터(재시도 포함) 실패하면 그 leg의 실패 status를 그대로 사용한다. `mode`는 이 조합 전용으로 추가한 `WalkMode.WAYPOINT`를 쓴다.
- 아직 `route_service.py`/`walk_router.py`(API)와는 연동하지 않았다 — `route_engine` 안에서만 호출 가능하다. 챗봇 연동을 포함한 leg별 `profile`/`custom_weights` 지정은 아직 지원하지 않고, 현재는 `WaypointComposerEngine` 생성자의 공통 `custom_weights`/`profile` 값을 모든 leg에 동일하게 적용한다.

## GPS Art

경유지 반영 경로를 응용해, 도형 모양대로 걷는 경로를 생성한다. route_engine 계산(`GpsArtEngine`)과 이미지 생성·윤곽선 추출(`GpsArtService`, `src/service/route/gps_art_service.py`) 두 layer로 나뉜다.

**`GpsArtEngine`(`gps_art.py`, route_engine 계산)**

- 입력은 `GpsArtRouteInput`(`src/schema/route_schema.py`): `shape_points`(정규화된 도형 좌표, 로컬 단위·단위 없음), `origin_lat`/`origin_lon`(배치할 중심 위경도), `target_km`(목표 총 이동 거리). `shape_points`는 검증 시점에 첫 점=마지막 점이 되도록 자동으로 닫힌다.
- `_map_to_geo`: `shape_points`를 실제 위경도로 변환한다. 도형의 로컬 단위 둘레와 `target_km`(도로망 계수 1.4로 나눠 직선 기준으로 역산)의 비율로 scale을 구하므로, 입력 좌표가 어떤 절대 크기·단위든 상관없이 항상 `target_km`에 맞게 배치된다(스케일 불변).
- `_snap_to_nodes`: 변환된 위경도를 그래프 최근접 노드로 스냅한다. 연속으로 같은 노드에 스냅되면(도로망이 성긴 구간) 하나로 합친다.
- 스냅된 노드열을 `WaypointRouteInput`으로 변환해 `WaypointComposerEngine`에 위임한다. 도형 왜곡을 막기 위해 모든 leg를 `oneway_shortest`로 고정한다(profile/custom_weights 영향 배제).
- `WaypointComposerEngine`과 마찬가지로 그래프를 mutate하지 않아 `G.copy()`를 하지 않는다.
- 최종 응답의 `mode`는 `WaypointComposerEngine`이 채우는 `WAYPOINT`를 `GPS_ART`로 덮어써서 반환한다.

**`GpsArtService`(`src/service/route/gps_art_service.py`, 이미지→좌표 준비)**

- `get_shape_points(access_token, shape_name)`(async): 인증 확인 → `pictures/{shape_name}.png` 캐시 확인(있으면 재사용, 없으면 `GPTClient.generate_image()`로 생성 후 저장) → OpenCV로 배경 제거·윤곽선 추출 → `List[GpsArtPoint]`(정규화된 도형 좌표, 위경도 아님) 반환.
- 윤곽선 단순화는 균등 간격 샘플링이 아니라 `cv2.approxPolyDP`(Douglas-Peucker)를 쓴다 — 직선 구간은 점 간격과 무관하게 양 끝점만 남고, 곡선은 굴곡에 따라 필요한 만큼만 점이 남는다.
- 반환값의 절대 스케일은 정규화(원점 이동·y축 반전만 함)하지 않는다 — `GpsArtEngine._map_to_geo`가 어차피 `target_km` 비율로 다시 계산하기 때문에 여기서 크기를 맞출 필요가 없다.
- 이 서비스는 `route_engine`과 달리 외부 API(OpenAI Images API)를 직접 호출한다 — `GpsArtEngine`(route_engine)은 여전히 이 경계를 지킨다.
- 이미지 생성 프롬프트는 `src/prompt/gps_art_image.yaml`(스타일 고정: 흰 배경·굵은 검은 실루엣·장식 없음). 런타임에서 `cv2`(`opencv-python`)를 실제로 쓰므로 `pyproject.toml`/`requirements.txt`에 의존성으로 선언돼 있다.

**설계 의도(아직 미구현)**: 챗봇 연동 시 extractor 단계는 이미지 생성·좌표 추출(`GpsArtService.get_shape_points`)까지만 하고 실제 경로 계산(`GpsArtEngine`)은 하지 않을 계획이다 — `ModeTool`(추출, 실행 없음)과 `RouteTool`+`RouteExecutor`(실행)가 나뉜 기존 패턴과 동일하게, GPS Art도 "추출 단계는 실행하지 않는다"는 원칙을 따르기 위함이다. 현재는 `route_service.py`/`walk_router.py`(API)/챗봇 어디와도 연동돼 있지 않다.

## 영역 경계

- 외부 API와 LLM을 직접 호출하지 않습니다.
- HTTP 요청·응답을 처리하지 않습니다.
- 데이터 원본을 직접 적재하지 않습니다.
- 입력 Graph와 Profile을 받아 경로 계산 결과를 반환합니다.

## V1 점수 방향

- 안전·자연·공원·랜드마크·러닝·편의·접근성 값은 확인된 Edge에만 제한 가점한다.
- 데이터가 없는 지역의 `0`은 감점이 아니라 중립이다.
- `slope_score`는 평탄도이며 `1.0`에 가까울수록 평지다.
- `is_vehicle_caution`은 `child` 가중치에 따른 회피 페널티다. `child_score` 자체는 안전 가점으로 사용하지 않는다.
- 터널·육교·지하철망·건물 내부는 완전 차단하지 않고 보수적인 쾌적도 페널티를 적용한다.
- `blocked_tags`에 명시된 검증된 WalkEdge Tag만 탐색 비용을 무한대로 만들어 제외한다.
- 기본 프로필은 실재하지 않는 `underground` Tag를 자동 차단하지 않는다.

프로필에는 기존 유형 외에 `convenient`, `accessible`이 있다.
내부 `accessible`은 사용자에게 `이동이 편한 길`로 표시한다. 리프트·엘리베이터
인접 Edge와 평탄한 길을 제한적으로 선호할 뿐, 완전한 무장애 경로를 보장하지 않는다.
