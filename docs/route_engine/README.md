# 경로 생성 엔진

> 상태: Current  
> 기준일: 2026-07-24  
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
