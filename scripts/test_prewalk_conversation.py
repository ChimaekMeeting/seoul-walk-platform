"""
챗봇 prewalk 대화 흐름 시나리오 테스트 스크립트.

실행: DB에 가장 최근 저장된 카카오 사용자를 자동으로 사용한다.
poetry run python scripts/test_prewalk_conversation.py
"""
import asyncio
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 한글 출력 깨짐 방지 (Windows 콘솔)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from dotenv import load_dotenv

load_dotenv(encoding="utf-8")

from sqlalchemy import select

from src.database.postgresql import get_postgresql_db
from src.entity.user import Provider, User
from src.interfaces import dependencies
from src.interfaces.schema.prewalk_schema import ChatResponse

def _latest_kakao_provider_id() -> str | None:
    """
    로컬 DB에 가장 최근 저장된 카카오 사용자의 provider_id를 조회합니다.
    """
    with get_postgresql_db() as db:
        query = (
            select(User.provider_id)
            .where(User.provider == Provider.KAKAO)
            .order_by(User.created_at.desc())
            .limit(1)
        )
        return db.execute(query).scalar_one_or_none()

# 서울시청
LAT, LON = 37.5665, 126.9780

# 턴 하나는 (user_prompt, confirmation)이다. confirmation은 FE 버튼 값(2026-09-24부터
# ConfirmationClassifier 대신 이 필드로 확인 응답을 판정한다) — None이면 안 보낸 것(자유
# 텍스트만 보낸 턴), True/False면 실제 버튼 클릭이다. YES는 그 자체로 "예" 버튼 클릭 한
# 턴(user_prompt 없음)을 뜻하는 sentinel이다.
Turn = tuple[str, Optional[bool]]
YES: Turn = ("", True)


def NO(user_prompt: str = "") -> Turn:
    """"아니요" 버튼 클릭(user_prompt에 교정 내용을 곁들일 수 있음)."""
    return (user_prompt, False)


def SAY(user_prompt: str) -> Turn:
    """버튼 없이 자유 텍스트만 보낸 턴(확인 대기 중이면 무조건 부정 처리됨, 2026-09-24부터)."""
    return (user_prompt, None)


# (번호, 시나리오 설명, [턴 목록], 검증 포인트)
# 시나리오 목록의 단일 기준은 docs/chatbot/test_scenarios.md이며, 이 표를 바꾸면 그 문서도 함께 갱신한다.
# 2026-09-25 후속: ConfirmationClassifier(LLM 기반 자유 텍스트 긍정/부정 판정) 제거로
# 3/9/11번 시나리오의 확인 응답 방식이 바뀌었다 — 상세는 docs/chatbot/agent_harness.md
# "2026-09-24"/"2026-09-25 후속" 참고.
SCENARIOS: list[tuple[int, str, list[Turn], str]] = [
    (1, "서비스 지역 밖(서울과 인접한 도보망 밖 지명)",
        [SAY("의정부역에서 3km 순환 산책하고 싶어")],
        "서울과 가까운 서울 밖 지명 처리 -> bbox 필터로 서울 밖 안내가 나오는지(_SEOUL_BBOX 사각형 밖 + Kakao 검색 반경 안이어야 out_of_seoul 경로를 탈 수 있음)"),
    (2, "무관한 발화(Extractor) - 첫 턴부터 산책과 무관",
        [SAY("주말에 볼만한 영화 추천해줘")],
        "mode/context가 비고 Interviewer가 기본 정보를 재질문하는지"),
    (3, "무관한 발화(confirmation 미전송) - 확인 대기 중 버튼 없이 무관한 메시지",
        [SAY("여의도공원에서 2km 순환 코스로 산책할래"), SAY("오늘 날씨 어때?")],
        "확인 대기 중 confirmation 없이 무관한 메시지만 보내면 부정 처리되는지(2026-09-24부터 판정 자체가 결정론적)"),
    (4, "모드-순환 기본 흐름",
        [SAY("여의도공원에서 2km 순환 코스로 산책하고 싶어"), YES],
        "select_circular 정상 추출 -> 확인 대기 -> 긍정(confirmation=True) -> RouteExecutor 진입"),
    (5, "모드-편도 기본 흐름",
        [SAY("성수역에서 뚝섬역까지 2km 정도 예쁜 강변길로 걷고 싶어"), YES],
        "select_oneway(target_km 포함) 정상 추출 -> 확인 대기 -> 긍정(confirmation=True) -> RouteExecutor 진입"),
    (6, "모드-편도 최단 기본 흐름",
        [SAY("잠실역에서 강남역까지 최단 경로로 가고 싶어"), YES],
        "select_oneway_shortest(target_km 없음) 정상 추출 -> 확인 대기 -> 긍정(confirmation=True) -> RouteExecutor 진입"),
    (7, "Interviewer - 정보 부족 재질문(목적지 없음)",
        [SAY("편도로 2km 걷고 싶어")],
        "목적지 누락이 감지되어 재질문하는지"),
    (8, "Interviewer - 장소 검색 실패(존재하지 않는 지명)",
        [SAY("아리스토텔레스빌리지에서 걷고 싶어")],
        "Kakao 검색 결과 0건일 때 반응"),
    (9, "Interviewer - 확인 대기 중 버튼 없이 다른 경로 요청",
        [SAY("안국역에서 4km 순환 산책하고 싶어"), SAY("다른 경로로 해줄 수 있어?")],
        "확정 전 대체 요청(confirmation 미전송)에 어떻게 반응하는지 — 부정 처리 후 Extractor가 이 텍스트로 뭔가 추출하는지"),
    (10, "Interviewer - 출발지=목적지 장소명 명시",
        [SAY("신촌역에서 신촌역으로 가는 길 알려줘"), YES],
        "origin=destination으로 동일하게 명시됐을 때 확인 질문·긍정(confirmation=True) 후 RouteExecutor 처리 방식"),
    (11, "확인 대기 중 자연어만으로는 확정되지 않는지(버튼 없음)",
        [SAY("광화문역에서 경복궁까지 가줘"), SAY("그걸로 해줘")],
        "2026-09-24부터 confirmation 필드 없이는 '그걸로 해줘'처럼 강한 긍정 뉘앙스의 자유 텍스트도 절대 확인되지 않아야 한다(is_complete=False 유지) — 과거 ConfirmationClassifier가 있을 때는 긍정으로 판정됐던 케이스"),
]


async def _run_intent(
    orchestrator: dependencies.PrewalkOrchestrator,
    access_token: str,
    thread_id: str,
    user_prompt: str,
    confirmation: Optional[bool],
) -> Optional[ChatResponse]:
    """orchestrator()는 async generator다(2026-09-25 후속) — progress 이벤트는 화면에
    찍어주고, 마지막 result 이벤트만 반환한다."""
    chat: Optional[ChatResponse] = None
    async for kind, data in orchestrator.orchestrator(
        access_token, thread_id, user_prompt, LAT, LON, confirmation=confirmation,
    ):
        if kind == "progress":
            print(f"    [progress] {data}")
        else:
            chat = data
    return chat


async def _run_scenario(
    orchestrator: dependencies.PrewalkOrchestrator,
    access_token: str,
    no: int,
    desc: str,
    turns: list[Turn],
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

    for turn_no, (user_prompt, confirmation) in enumerate(turns, start=1):
        label = user_prompt if user_prompt else f"[confirmation={confirmation}]"
        print(f"  turn {turn_no} 입력: {label}")
        chat = await _run_intent(orchestrator, access_token, thread_id, user_prompt, confirmation)
        if chat is None or chat.state is None:
            status = chat.status if chat is not None else "no_result_event"
            print(f"  turn {turn_no} 실패: status={status}")
            return

        state = chat.state
        print(f"    mode={state.mode} awaiting_confirmation={state.awaiting_confirmation} is_complete={state.is_complete}")
        if state.user_context is not None:
            print(f"    context={state.user_context.model_dump(mode='json')}")
        if state.route_result is not None:
            print("    response=경로를 생성했어요.")
        else:
            print(f"    response={state.response}")
    print()


async def main() -> None:
    provider_id = _latest_kakao_provider_id()
    if not provider_id:
        raise SystemExit(
            "로컬 DB(users 테이블)에 카카오 사용자가 없습니다. 안드로이드 앱으로 한 번 로그인해 사용자를 만드세요."
        )
    print(f"DB에서 가장 최근 카카오 사용자를 사용합니다: {provider_id}")

    dependencies.init_route_service()
    orchestrator = dependencies.get_prewalk_orchestrator()
    access_token = dependencies.auth_service.get_access_token(Provider.KAKAO, provider_id)

    for no, desc, turns, expect in SCENARIOS:
        await _run_scenario(orchestrator, access_token, no, desc, turns, expect)


if __name__ == "__main__":
    asyncio.run(main())
