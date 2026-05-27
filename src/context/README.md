# Context Layer

## 1. 목적 및 역할
현재 상황 정보(날씨, 미세먼지, 카카오맵 주변 POI, 현재 위치 등)를 `application`, `agent`, `route_engine` 계층이 공통으로 사용하기 쉽도록 **표준화(Normalization)**하는 계층입니다.

이 계층은 산책 추천의 **Layer 1.5**에 해당합니다.
정적 도로망/안전/자연/경사 데이터가 Layer 1이라면, Context는 요청 시점마다 달라지는 날씨, 미세먼지, 주변 편의시설, 현재 위치를 다룹니다.

## 2. 외부 클라이언트와의 차이
- **이 계층은 외부 API Client가 아닙니다.** 
- 외부 API(기상청, 카카오 API 등) 통신은 `infrastructure/external` 계층이 담당하며, Context 계층은 인프라 계층이 받아온 순 날것의 데이터(raw data)를 서비스 내부 규격으로 예쁘게 포장하는 역할만 합니다.

## 3. 금지사항
- DB query 금지
- 외부 API 통신 금지
- `route_engine`의 feature/profile/scoring 직접 수정 금지

## 4. 활용
- `application`과 `agent`는 이 Context 데이터를 조합해서 `RouteRequest`를 생성하거나 유저에게 보여줄 `UIEvent`를 생성하는 데 활용합니다.
- `route_engine`은 필요한 경우 이미 표준화된 Context만 입력으로 받습니다. Context 계층이 route_engine 내부 feature/profile/scoring을 직접 조작하지 않습니다.

## 5. 현재 단계
- 실제 API 호출, DB 조회, geocoding, POI 검색은 구현하지 않습니다.
- class skeleton에는 필드 이름과 타입 힌트만 둡니다.
- 함수는 역할/입력/출력/TODO를 설명하고 `pass` 상태로 유지합니다.
