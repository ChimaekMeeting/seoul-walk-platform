# Domain Layer

## 1. 목적
이 계층은 외부 프레임워크(FastAPI, Streamlit, SQLAlchemy, NetworkX 등)와 완전히 독립적인 시스템의 **핵심 데이터 계약(Contract)**입니다.
현재 scaffold 단계에서는 순수 Python type hints 중심으로 필드 이름과 데이터 형태만 고정하며, 필요하면 추후 dataclass 또는 Pydantic 모델로 전환할 수 있습니다.

## 2. Schemas와 Domain의 차이
- **Schemas (`src/schemas`)**: 프론트엔드와 주고받는 API 형태(JSON)에 강하게 결합되어 있으며 자주 변경될 수 있습니다.
- **Domain (`src/domain`)**: 서비스 내부의 핵심 비즈니스 개념이므로, 외부의 변화(API 규격 변경 등)에 흔들리지 않는 가장 안정적인 뼈대입니다.

## 3. 의존성 규칙
- `route_engine`은 이 `domain` 계약을 기준으로 입력과 출력을 맞춥니다.
- `application`과 `agent` 계층도 이 `domain`을 기준으로 데이터를 조립합니다.

## 4. UI Event
- `frontend`는 도메인에서 정의된 `UIEvent` 명세서에 따라 화면(렌더링)을 그립니다.

## 5. 유의사항
- 이 단계에서는 실제 검증 로직을 구현하지 않고 뼈대(Skeleton)만 유지합니다.
