# 경로 생성 엔진

> 상태: Current
> 기준일: 2026-07-30
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
