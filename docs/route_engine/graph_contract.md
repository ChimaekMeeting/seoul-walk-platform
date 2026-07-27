# 경로 그래프 계약

> 상태: Current  
> 기준일: 2026-07-24  
> 관련 코드: `src/route_engine/graph/`, `src/repository/network/graph_repository.py`

## 목적

DB/PostGIS에서 조회한 도보망을 경로 생성 엔진이 사용할 수 있는 NetworkX Graph 형태로 준비합니다.

## 책임

- 주변 도보망 Graph 로드
- 표준 Node·Edge 속성 전달
- 통행 조건 및 차단 tags 기반 필터링
- Graph 직렬화 보조

## 금지사항

- Layer 또는 Score 계산
- Profile 가중치 결정
- 순환·편도 경로 탐색 실행
- FastAPI 또는 챗봇 코드 직접 의존
- 데이터 원본 직접 적재
