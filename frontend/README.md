# Frontend Layer

## 1. 개요
프론트엔드 계층은 렌더링(Rendering)만을 담당하는 얇은 클라이언트(Thin Client)입니다.

## 2. 핵심 원칙
- 프론트는 날씨 API, Kakao API, DB, `route_engine` 등을 절대 직접 호출하지 않습니다.
- 프론트는 백엔드가 반환한 표준화된 `UIEvent` 목록을 바탕으로 수동적으로 화면을 그리기만 합니다.

## 3. 구조
- `streamlit_prototype`: 백엔드 API와의 계약(Contract)을 검증하기 위한 임시 클라이언트 구조입니다.
- `mobile_app`: 미래에 React Native 앱이 위치할 공간입니다.
- **주의:** 기존 루트 디렉터리에 있는 `app.py` 등의 파일들은 현재 단계에서 수정하거나 이동하지 않습니다.
