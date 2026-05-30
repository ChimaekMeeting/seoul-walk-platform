# Streamlit Prototype

## 1. 목적
- 나중에 React Native 앱(`mobile_app`)이 호출할 백엔드 API 계약을 가장 먼저 검증해 보는 용도로 쓰입니다.

## 2. 구조
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
- `components/`: UI 컴포넌트를 기능 단위로 분류합니다. components 내부에 새로운 폴더를 만들거나 폴더명을 수정해도 됩니다.

## 3. 파일 명명 규칙
- `api/`: `{기능}_router.py`
- `schema/`: `{기능}_schema.py`
- `components/{분류}/`: `{기능}_{분류}.py`

## 4. 코드 작성 규칙
- 클래스로 작성합니다.
- 각 컴포넌트는 `render()` 메서드를 통해 UI를 출력합니다.

## 5. 주석 가이드라인
- 주석은 `"""\n~~\n"""` 형식을 준수합니다.
