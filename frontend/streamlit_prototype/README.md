# Streamlit Prototype

## 1. 목적
- 기존 루트 `app.py`를 당장 대체하지 않습니다.
- 이 폴더는 미래 Streamlit 기반의 프론트 리팩토링 목표 구조입니다.
- 나중에 React Native 앱(`mobile_app`)이 호출할 백엔드 API 계약을 가장 먼저 검증해 보는 용도로 쓰입니다.

## 2. 얇은 렌더러(Thin Renderer)
- 이 Prototype은 얇은 렌더러여야 합니다.
- 비즈니스 로직(길찾기, 필터링 등)은 무조건 `backend`, `application`, `agent`, `route_engine`에 둡니다.

## 3. 금지사항
- 이 단계(뼈대 생성 단계)에서는 실제 `streamlit` 임포트 및 구현을 금지합니다.
