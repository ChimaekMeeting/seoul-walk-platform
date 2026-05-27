# Repositories

**목적:** DB query 구현체가 위치할 예정인 계층입니다. `domain`이나 `application` 계층이 DB의 세부사항(SQLAlchemy, 쿼리문 등)을 몰라도 되도록 감싸는(Wrap) 역할을 합니다.

**금지사항:**
- 현재 단계에서 실제 query 구현 금지
- 기존 repository 임포트 금지

**데이터 저장 기준:**
- 실시간 카카오맵 POI 전체를 무조건 저장하지 않습니다.
- 정적 Layer 1로 쓸 가치가 있는 검증된 시설 데이터만 저장 대상으로 봅니다.
- application/domain/route_engine은 SQLAlchemy, SQL, PostGIS 세부사항을 몰라야 합니다.

**추후 마이그레이션:**
- 기존 `src/repository` 코드는 바로 이동하지 않습니다.
- 충분한 테스트와 팀 합의 후 이 구조에 맞춰 점진적으로 이동합니다.
