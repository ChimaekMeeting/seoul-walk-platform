# Database Configuration & Entities

**목적:** DB 연결과 ORM entity가 위치할 예정인 계층입니다.

**금지사항:**
- 현재 단계에서 SQLAlchemy 임포트 금지
- 실제 session 구현 금지
- 기존 `src/entity` 이동 금지
- 기존 `src/database` 수정 금지

**마이그레이션 예정:**
추후 기존 `src/entity`와 `src/database`가 이 위치(`infrastructure/db/` 및 `infrastructure/db/entities/`)로 이동될 수 있습니다.
