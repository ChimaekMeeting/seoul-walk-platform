"""
챗봇 prewalk 대화 흐름 시나리오 테스트 스크립트.

Graph를 별도로 조립하지 않고, 실제 서비스가 쓰는 것과 동일한 초기화·호출 경로를 그대로 탄다:
`src.interfaces.dependencies.init_route_service()`로 PrewalkOrchestrator 싱글톤을 만들고,
`PrewalkOrchestrator.get_init_message`/`orchestrator`를 시나리오별로 직접 호출한다.

로컬 PostgreSQL·Valkey가 필요하고(실제 서비스와 동일 경로), init_route_service()가 Postgres에서
전체 도보 그래프를 로딩하므로 첫 실행에 수 초 이상 걸릴 수 있다.

사전 준비:
- .env에 OPENAI_API_KEY, ACCESS_SECRET_KEY, KAKAO_API_KEY, POSTGRES_*, VALKEY_URI 설정
- 로컬 DB(users 테이블)에 이미 존재하는 사용자의 provider_id를 TEST_PROVIDER_ID 환경변수로 지정
  (안드로이드 앱으로 카카오 로그인해서 만든 계정의 provider_id)

실행: TEST_PROVIDER_ID=... poetry run python scripts/test_prewalk_conversation.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 한글 출력 깨짐 방지 (Windows 콘솔)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from dotenv import load_dotenv

load_dotenv(encoding="utf-8")

from src.entity.user import Provider
from src.interfaces import dependencies
from src.interfaces.schema.prewalk_schema import ChatResponse

TEST_PROVIDER_ID = os.getenv("TEST_PROVIDER_ID", "")

# 현재 위치(서울시청)
LAT, LON = 37.5665, 126.9780

# (번호, 시나리오 설명, [턴별 사용자 발화], 검증 포인트)
SCENARIOS: list[tuple[int, str, list[str], str]] = [
    (1, "순환 경로 기본 흐름 + 명시적 긍정",
        ["한적하고 그늘진 길로 3km 걷고 싶어", "응 좋아"],
        "확인 대기 -> 긍정 판정 -> RouteExecutor 진입"),
    (2, "부정 + 수정 정보(거리 변경) -> Extractor 재진입",
        ["2호선 강남역에서 출발해서 5km 순환 산책", "아니 3km로 바꿔줘", "응"],
        "1차 부정 후 target_km 수정 반영 -> 재확인 대기 -> 긍정"),
    (3, "명시적 단어 없는 애매한 긍정(구 하드코딩 단어 목록엔 없던 표현)",
        ["광화문역에서 인스타 감성 카페거리까지 가줘", "그걸로 해줘"],
        "'그걸로 해줘'가 긍정으로 판정되는지"),
    (4, "확인 대기 중 무관한 응답 -> 부정 처리",
        ["여의도공원에서 2km 순환 코스로 산책할래", "오늘 날씨 어때?"],
        "확인 대상과 무관한 응답이 부정으로 판정되는지"),
    (5, "출발지=목적지 장소명, 명시적 출발 표현 없음",
        ["용산역으로 가는 길 알려줘"],
        "origin은 null로 남고(용산역은 목적지로만 처리) 위치 보완 질문이 나오는지"),
]


async def _run_scenario(
    orchestrator: dependencies.PrewalkOrchestrator,
    access_token: str,
    no: int,
    desc: str,
    turns: list[str],
    expect: str,
) -> None:
    print("=" * 78)
    print(f"[시나리오 {no}] {desc}")
    print(f"검증 포인트: {expect}")

    init: ChatResponse = await orchestrator.get_init_message(access_token, LAT, LON)
    if init.thread_id is None:
        print(f"  init 실패: status={init.status}")
        return
    thread_id = init.thread_id

    for turn_no, user_prompt in enumerate(turns, start=1):
        print(f"  turn {turn_no} 입력: {user_prompt}")
        chat: ChatResponse = await orchestrator.orchestrator(access_token, thread_id, user_prompt)
        if chat.state is None:
            print(f"  turn {turn_no} 실패: status={chat.status}")
            return

        state = chat.state
        print(f"    mode={state.mode} awaiting_confirmation={state.awaiting_confirmation} is_complete={state.is_complete}")
        if state.user_context is not None:
            print(f"    context={state.user_context.model_dump(mode='json')}")
        if state.route_result is not None:
            print(f"    route: status={state.route_result.status} total_km={state.route_result.total_km}")
        print(f"    response={state.response}")
    print()


async def main() -> None:
    if not TEST_PROVIDER_ID:
        raise SystemExit("TEST_PROVIDER_ID 환경변수를 설정하세요 (로컬 DB에 이미 존재하는 사용자의 provider_id).")

    dependencies.init_route_service()
    orchestrator = dependencies.get_prewalk_orchestrator()
    access_token = dependencies.auth_service.get_access_token(Provider.KAKAO, TEST_PROVIDER_ID)

    for no, desc, turns, expect in SCENARIOS:
        await _run_scenario(orchestrator, access_token, no, desc, turns, expect)


if __name__ == "__main__":
    asyncio.run(main())
