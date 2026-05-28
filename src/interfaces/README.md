# Interfaces Layer

## 1. 소개
- FE와 직접 소통하는 진입점입니다.
- 구조는 아래와 같습니다.
```
- dependencies.py
- api/
- schema/
```

## 2. 싱글톤 패턴 준수
- service 계층의 클래스를 interfaces/dependencies.py에서 단 한 번만 선언하여, 이를 전역적으로 공유합니다.
- dependencies.py에서 선언한 인스턴스는 api 파일에서 아래와 같이 사용할 수 있습니다.
```
@router.get("/users/me")
def get_my_profile(user_service: UserService = Depends(get_user_service)):
    return user_service.get_profile(...)
```

# 3. schema 작성 규칙
- 기본적으로 BaseModel을 상속받는 클래스로 작성합니다. BaseModel은 데이터 구조가 깨지는 것을 방지합니다.

## 4. 명칭 규칙
- api 내 파일명은 {기능}_router.py로 통일합니다.
- schema 내 파일명은 {schema}_router.py로 통일합니다.

## 5. 주석 작성 규칙
- """\n~~~\n""" 형식에 맞게 작성합니다.

## 6. 주의사항
- 구현한 API는 main.py에 `app.include_router({기능}_router.router)`를 명세해야 동작합니다.