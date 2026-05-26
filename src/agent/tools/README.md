# Agent Tools

**목적:** Agent가 직접 외부 세계(API, DB)나 복잡한 알고리즘(Route Engine)에 접근하지 않고, 대리 호출을 통해 작업을 수행할 수 있도록 만들어진 어댑터(Adapter)들입니다.

**금지사항:**
- 이곳에서도 실제 `requests` 등 HTTP 호출이나 라우팅 수학 연산을 구현하지 않습니다. 오직 `infrastructure`나 `route_engine`에 대한 연결(Delegation)만 담당합니다.
