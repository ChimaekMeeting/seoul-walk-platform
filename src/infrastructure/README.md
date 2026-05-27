# Infrastructure Layer

## 1. 목적 및 역할
infrastructure는 데이터베이스, 외부 API, 캐시 등 외부 세계와 연결되는 모든 구체적인 기술적 구현(Implementation) 계층입니다.

## 2. 의존성 격리
- `application`, `domain`, `route_engine`은 이곳의 세부 구현사항(외부 API, DB, cache)을 전혀 몰라야 합니다.
- 이 계층의 변경(예: MySQL -> PostgreSQL 변경, Kakao API -> Naver API 변경)이 다른 내부 계층에 영향을 주어서는 안 됩니다.

## 3. 데이터 흐름 규칙
- Kakao Map API 등의 raw response는 `external/kakao_client.py`에서 그대로 받아옵니다.
- 하지만 이 raw data를 다른 서비스 레이어로 바로 넘기지 않고, `context/live_poi_context.py` 등에서 서비스 내부 표준 규격으로 한 번 포장(Standardization)하여 전달합니다.

예상 흐름:

```text
external/kakao_client.py
  -> raw Kakao response
context/live_poi_context.py
  -> standard POI context
application/route_recommendation
  -> RouteContext 조립
application/ui_events
  -> poi_overlay UIEvent 생성
frontend
  -> 지도 마커 렌더링
```

## 4. DB 저장 원칙 (실시간 vs 정적 데이터)
- 실시간 POI 데이터는 무조건 DB에 영구 저장하지 않습니다. 기본적으로 request context나 `cache/`에 머뭅니다.
- 길찾기의 기준(Layer 1)으로 쓸 가치가 있는 정적인 시설 데이터만 data collector를 거쳐 `repositories/`를 통해 DB(PostGIS)에 저장됩니다.

구분:

```text
Layer 1 정적 데이터:
  - 공공 화장실, 경찰서, 공원, 하천, 경사도, 안심시설 등
  - PostGIS 저장 대상

Layer 1.5 실시간 데이터:
  - 현재 요청 시점의 카카오맵 주변 POI, 날씨, 미세먼지
  - request context 또는 짧은 TTL cache 대상
```

## 5. 기존 파일들과의 관계 (마이그레이션 예정)
- 현재 존재하는 `src/client`, `src/repository`, `src/entity`, `src/database` 파일들은 건드리지 않습니다.
- 본 스캐폴드는 미래의 구조를 보여주는 것이며, 추후 기존 폴더들이 이 `infrastructure/` 하위 구조로 마이그레이션 될 예정입니다.
