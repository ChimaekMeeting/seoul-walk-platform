# Streamlit Prototype

## 1. 목적
- 기존 루트 `app.py`를 당장 대체하지 않습니다.
- 이 폴더는 미래 Streamlit 기반의 프론트 리팩토링 목표 구조입니다.
- 나중에 React Native 앱(`mobile_app`)이 호출할 백엔드 API 계약을 가장 먼저 검증해 보는 용도로 쓰입니다.

## 2. 얇은 렌더러(Thin Renderer)
- 이 Prototype은 얇은 렌더러여야 합니다.
- 비즈니스 로직(길찾기, 필터링 등)은 무조건 `backend`, `application`, `agent`, `route_engine`에 둡니다.

## 3. 구조
```
app.py
api/
schema/
components/
    button/
    card/
    carousel/
    layer/
    map/
    page/
    panel/
    sidebar/
```
- `app.py`: 앱 진입점. 각 컴포넌트를 조합하여 페이지를 렌더링합니다.
- `api/`: 백엔드 API 호출을 담당합니다.
- `schema/`: API 요청/응답 데이터 구조를 정의합니다.
- `components/`: UI 컴포넌트를 기능 단위로 분류합니다.

## 4. 파일 명명 규칙
- `api/`: `{기능}_router.py`
- `schema/`: `{기능}_schema.py`
- `components/{분류}/`: `{기능}_{분류}.py`

## 5. 코드 작성 규칙
- 클래스로 작성합니다.
- 각 컴포넌트는 `render()` 메서드를 통해 UI를 출력합니다.
- 주석은 `"""\n~~\n"""` 형식을 준수합니다.

## 6. 금지사항
- 비즈니스 로직을 컴포넌트 내부에 작성하지 않습니다.
