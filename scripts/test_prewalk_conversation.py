"""
챗봇 prewalk 대화 흐름 시나리오 테스트 스크립트.

실행: DB에 가장 최근 저장된 카카오 사용자를 자동으로 사용한다.
poetry run python scripts/test_prewalk_conversation.py
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

# (번호, 시나리오 설명, [턴별 사용자 발화], 검증 포인트)
# 시나리오 목록의 단일 기준은 docs/chatbot/test_scenarios.md이며, 이 표를 바꾸면 그 문서도 함께 갱신한다.
SCENARIOS: list[tuple[int, str, list[str], str]] = [
    (1, "서비스 지역 밖(서울과 인접한 도보망 밖 지명)",
        ["의정부역에서 3km 순환 산책하고 싶어"],
        "서울과 가까운 서울 밖 지명 처리 -> bbox 필터로 서울 밖 안내가 나오는지(_SEOUL_BBOX 사각형 밖 + Kakao 검색 반경 안이어야 out_of_seoul 경로를 탈 수 있음)"),
    (2, "무관한 발화(Extractor) - 첫 턴부터 산책과 무관",
        ["주말에 볼만한 영화 추천해줘"],
        "mode/context가 비고 Interviewer가 기본 정보를 재질문하는지"),
    (3, "무관한 발화(ConfirmationClassifier) - 확인 대기 중 무관한 응답",
        ["여의도공원에서 2km 순환 코스로 산책할래", "오늘 날씨 어때?"],
        "확인 대상과 무관한 응답이 부정으로 판정되는지"),
    (4, "모드-순환 기본 흐름",
        ["여의도공원에서 2km 순환 코스로 산책하고 싶어", "응"],
        "select_circular 정상 추출 -> 확인 대기 -> 긍정 -> RouteExecutor 진입"),
    (5, "모드-편도 기본 흐름",
        ["성수역에서 뚝섬역까지 2km 정도 예쁜 강변길로 걷고 싶어", "응"],
        "select_oneway(target_km 포함) 정상 추출 -> 확인 대기 -> 긍정 -> RouteExecutor 진입"),
    (6, "모드-편도 최단 기본 흐름",
        ["잠실역에서 강남역까지 최단 경로로 가고 싶어", "응"],
        "select_oneway_shortest(target_km 없음) 정상 추출 -> 확인 대기 -> 긍정 -> RouteExecutor 진입"),
    (7, "Interviewer - 정보 부족 재질문(목적지 없음)",
        ["편도로 2km 걷고 싶어"],
        "목적지 누락이 감지되어 재질문하는지"),
    (8, "Interviewer - 장소 검색 실패(존재하지 않는 지명)",
        ["아리스토텔레스빌리지에서 걷고 싶어"],
        "Kakao 검색 결과 0건일 때 반응"),
    (9, "Interviewer - 확인 대기 중 다른 경로 요청",
        ["안국역에서 4km 순환 산책하고 싶어", "다른 경로로 해줄 수 있어?"],
        "확정 전 대체 요청에 어떻게 반응하는지(무시/무관한 발화 취급/기타)"),
    (10, "Interviewer - 출발지=목적지 장소명 명시",
        ["신촌역에서 신촌역으로 가는 길 알려줘", "응"],
        "origin=destination으로 동일하게 명시됐을 때 확인 질문·긍정 후 RouteExecutor 처리 방식"),
    (11, "ConfirmationClassifier - 명시적 단어 없는 애매한 긍정",
        ["광화문역에서 경복궁까지 가줘", "그걸로 해줘"],
        "'그걸로 해줘'가 긍정으로 판정되는지"),
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
