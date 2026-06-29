"""
Extractor 단독 테스트 스크립트.

여러 프롬프트로 Extractor().run()을 직접 호출해 모드/추출 결과/테마를 출력한다.
실제 OpenAI 호출이 일어나므로 .env의 OPENAI_API_KEY가 필요하다.

실행: poetry run python scripts/test_extractor.py
"""
import asyncio
import json
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

from src.agent.nodes.extractor import Extractor
from src.schema.prewalk_schema import Location, State

# 현재 위치(서울시청) — origin 미언급/"현위치" 시 기본값으로 사용됨
CURRENT_LOCATION = Location(
    lat=37.5665, lon=126.9780,
    address="서울 중구 세종대로 110", place_name="서울특별시청",
)

# (번호, 프롬프트, 검증 포인트)
PROMPTS: list[tuple[int, str, str]] = [
    (1,  "한적하고 그늘진 길로 5km 걷고 싶어",         "circular, target_km=5.0, themes=[조용한/그늘이 많은]"),
    (2,  "800m만 살짝 걷고 올래",                     "circular, target_km=0.8(미터→km 변환), themes=[]"),
    (3,  "2호선 강남역에서 출발해서 3km 돌래",        "circular, origin=강남역(2호선), target_km=3.0"),
    (4,  "조깅하기 좋은 한강 코스 5km로",             "circular, target_km=5.0, themes=[뛰고 싶은/운동](조깅)"),
    (5,  "골목골목 구경하면서 천천히 2km",            "circular, target_km=2.0, themes=[골목골목/볼거리 많은]"),
    (6,  "반려동물이랑 산책할 만한 코스 추천해줘",    "circular(추천, 거리X→3.0), themes=[반려동물]"),
    (7,  "광화문역에서 인스타 감성 카페거리까지 가줘", "oneway_shortest, dest=카페거리?, themes=[인스타 감성]"),
    (8,  "집까지 걸어갈래",                           "oneway_shortest, dest=집(개인 장소 처리 관찰)"),
    (9,  "안녕! 오늘 날씨 좋다",                       "off-topic 인사 → select_none"),
    (10, "여의도공원이랑 반포한강공원 둘 다 들렀다 올래", "복수 목적지 — 어떻게 처리하는지 관찰"),
]


def _show(label: str, expect: str, state: State) -> None:
    print("=" * 78)
    print(f"입력   : {label}")
    if expect:
        print(f"기대   : {expect}")
    print(f"mode   : {state.mode}")
    if state.user_context is not None:
        ctx = json.dumps(state.user_context.model_dump(mode="json"), ensure_ascii=False)
        print(f"context: {ctx}")
    else:
        print("context: None (추출 안 됨)")
    print(f"themes : {state.themes}")


async def _run(extractor: Extractor, prompt: str, ctx=None) -> State:
    state = State(user_id=1, current_location=CURRENT_LOCATION, user_context=ctx)
    state.user_prompt = prompt
    return await extractor.run(state)


async def main() -> None:
    extractor = Extractor()

    # ── 단일 턴 테스트 ──────────────────────────────────────────────────────
    for num, prompt, expect in PROMPTS:
        try:
            state = await _run(extractor, prompt)
            _show(f"[{num}] {prompt}", expect, state)
        except Exception as e:
            print(f"[{num}] {prompt} → 오류: {e}")

    # ── 2턴 테스트: 지점만 변경(브랜드 유지) ────────────────────────────────
    print("\n" + "#" * 78)
    print("# 2턴 지점변경 테스트 (이전 컨텍스트 유지)")
    print("#" * 78)
    st1 = await _run(extractor, "스타벅스 광화문점까지 갈래")
    _show("[사전] 스타벅스 광화문점까지 갈래", "dest=스타벅스 광화문점", st1)
    st2 = await _run(extractor, "아니 강남점으로 갈래", ctx=st1.user_context)
    _show("[11] 아니 강남점으로 갈래", "dest=스타벅스 강남점(브랜드 유지)", st2)


if __name__ == "__main__":
    asyncio.run(main())
