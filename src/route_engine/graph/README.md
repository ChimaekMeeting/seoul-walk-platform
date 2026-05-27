# Graph

**목적:** DB/PostGIS 또는 application 계층에서 전달된 도로망을 route_engine이 사용할 수 있는 표준 graph 형태로 준비합니다.

**책임:**
- 주변 도로망 graph 로드 전략 정의
- route_engine 표준 node/edge attribute 이름 정리
- 필요 시 graph radius/filter 정책 정리
- 결과를 GeoJSON/좌표 리스트로 변환하기 전의 graph serialization 보조

**금지사항:**
- feature 점수 계산 금지
- profile weight 해석 금지
- 순환/편도 라우팅 알고리즘 실행 금지
- Streamlit/FastAPI 직접 import 금지
- 기존 `src/service/route` 로직 import 금지

