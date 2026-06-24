# 🚀 Route Engine

## 1. 이 폴더의 목적
순수 경로 계산 코어입니다. 외부 API, FastAPI 클라이언트, LLM 에이전트에 의존하지 않고 수학적/지리적 경로 탐색 기능만을 제공합니다.

## 2. 기존 `src/service/route/`와의 관계
기존 코드는 유지하되, 앞으로 모든 팀원의 새로운 라우팅 로직은 이 `route_engine` 내부의 3-Layer 규칙에 맞추어 분할되어야 합니다. 모든 이사가 완료된 후 기존 폴더는 폐기됩니다.

## 3. 각 폴더의 역할
- **features/**: 길의 객관적 속성 (CCTV, 공원 등)
- **profiles/**: 사용자 의도나 테마별 가중치 규칙
- **graph/**: PostGIS/DB에서 읽은 도로망을 route_engine 표준 graph 형태로 준비
- **scoring/**: features * profiles 결합 및 점수 계산
- **engines/**: 순환/편도 실제 경로 탐색 알고리즘
- **result/**: 최종 결과를 표준 포맷으로 조립

## 4. 팀원 작업 규칙
각자 할당받은 도메인(예: 조용한 길, 런닝 길)의 로직을 하나의 거대한 함수로 짜지 말고, Feature(데이터)와 Profile(가중치)로 분리해서 작성합니다.

## 5. 금지사항
- 기능 구현 외의 외부 API (Kakao, GPT) 직접 호출 금지
- FastAPI 라우터나 Streamlit 뷰 파일 임포트 금지
- 기존 `src/service/route` 파일 꼬리물기 식 임포트 금지

## 6. WalkMode vs ScoringProfile
경로 생성 방식과 점수 선호도는 서로 다른 축이며 독립적으로 조합됩니다.

- **WalkMode** (`src/interfaces/schema/walk_schema.py`): 경로를 *어떻게* 만들지 결정합니다.
  - `circular_random`, `oneway_shortest`, `oneway_random` 3개로 고정되어 있으며, 각각 별도의 엔진(`engines/circular_random.py`, `engines/dijkstra.py`, `engines/oneway_random.py`)에 매핑됩니다.
- **ScoringProfile** (`profiles.py`): 경로 비용을 계산할 때 *어떤 score를 선호*할지 결정합니다.
  - `default`, `nature`, `safe`, `flat`, `running`, `landmark` 6개이며, `ProfileConfig.weights`/`blocked_tags`/`scoring_mode`로 정의됩니다.
  - 어떤 WalkMode를 쓰든 같은 ScoringProfile은 항상 같은 weights를 줍니다(`get_profile(profile)`이 WalkMode를 모릅니다).
- 3개 엔진 생성자는 `(custom_weights, profile)`을 받아 `merge_weights(profile.weights, custom_weights)`로 최종 weights를 계산합니다. `custom_weights`는 명시적으로 지정한 필드만 profile 위에 override하고(부분 병합), 나머지는 profile의 base weights를 그대로 씁니다.
- `scoring_engine.py`의 계산 공식(`general`/`running` 분기)은 그대로이며, `ProfileConfig.scoring_mode`로 어느 분기를 쓸지만 선택합니다(현재 `running` profile만 `"running"` 분기 사용).

## 7. 추후 마이그레이션 순서
1. Skeleton 완성 (현재)
2. 팀원들이 본인 로직을 Skeleton으로 복사 (병렬 작업)
3. 충분한 테스트 후 API Gateway의 라우터 연결점을 기존 로직에서 `route_orchestrator.py`로 점진 전환
4. 기존 `src/service/route/`는 즉시 삭제하지 않고 deprecated 처리 후, 팀 합의와 동작 검증이 끝난 뒤 정리
