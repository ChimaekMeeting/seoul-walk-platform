"""
extraction.yaml 프롬프트 검증(eval) 스크립트.

`src/prompt/extraction.yaml`가 자연어 발화에서 **어떤 도구를 고르고 어떤 필드를
뽑는가**만 격리해서 확인한다. 라벨링된 케이스 목록을 실제 OpenAI 모델에 돌려
기대값과 대조하고, 케이스별 PASS/FAIL + 요약 + 종료 코드(실패 시 1)를 낸다.

검증 범위: 순환(select_circular) / 편도 우회(select_oneway) / 최단(select_oneway_shortest)
세 모드 + "도구 미호출"만 다룬다. GPS Art·경유지(waypoint)는 대상이 아니다.

[Current Context] 유지 검증(2026-09-13 추가, case_101~130): extraction.yaml [3]의
"부분 수정" 규칙 — 언급 안 한 필드는 유지, 언급한 필드만 변경, 모드는 명시적으로 다르게
요구했을 때만 변경 — 을 context를 채운 상태에서 30개로 검증한다. Extractor.run()이
tool_calls가 없으면 state를 그대로 반환하므로(예외1, extractor.py:91-94), "무관한 대화·
모호한 요청" 케이스는 "tool 미호출"만 확인해도 "context 값이 그대로 보존됐는지"까지
사실상 같이 검증된다. (2026-09-13 이전 버전은 같은 발화를 context 있음/없음으로 짝지어
대조했으나, context 유지 품질 자체를 넓게 보기 위해 전부 context 있는 케이스로 교체했다.)

- `scripts/test_prewalk_conversation.py`와의 차이: 저 스크립트는 Extractor +
  Interviewer + ConfirmationClassifier 전체 대화 흐름을 DB·Valkey·Kakao까지 실제로
  호출해 사람이 눈으로 보는 용도다. 이 스크립트는 DB/Valkey/Kakao를 전혀 쓰지 않는다
  (필요한 건 OPENAI_API_KEY뿐 — UserPreferenceRepository는 온보딩 선호값 없음으로 모킹).
- 각 케이스마다 raw tool_call(LLM이 낸 그대로)과, 그 raw 결과에 Extractor._apply_postprocessing()
  (예외3~10: 좌표 재검증, 모드 변경과 무관한 필드 보존, origin=null→현재위치, target_km/
  target_minutes 정리·온보딩 기본값 채움 등)을 적용한 후처리 결과를 **둘 다** 보여주고
  각각 별도로 PASS/FAIL을 매긴다(2026-09-13 추가). 후처리는 raw tool_call을 그대로
  재사용할 뿐 LLM을 새로 부르지 않는다 — 그래야 "같은 추출 결과의 전/후"가 된다.
  raw만 보고 싶으면(순수 프롬프트 신뢰도) `호출(raw)`/`결과(raw)` 줄만, 실제 State에
  반영될 값이 궁금하면 `호출(후처리)`/`결과(후처리)` 줄을 본다. 종료 코드는 raw 기준이다.
- 케이스 발화는 extraction.yaml의 few-shot 예시와 겹치지 않게 유지한다
  (규칙 일반화가 아니라 예시 암기를 검증하게 되므로 — docs/chatbot/test_scenarios.md 참고).

실행:
    ./.venv/Scripts/python.exe scripts/eval_extraction.py
    ./.venv/Scripts/python.exe scripts/eval_extraction.py --repeat 3 --verbose
    ./.venv/Scripts/python.exe scripts/eval_extraction.py --only circular_basic,oneway_keyword
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 콘솔 한글 깨짐 방지
except Exception:
    pass

from dotenv import load_dotenv

load_dotenv(encoding="utf-8")

from langchain_openai import ChatOpenAI

from src.interfaces import dependencies  # noqa: F401 — src.agent.nodes.* 순환 임포트 해소용 선행 임포트

from src.agent.nodes.extractor import Extractor
from src.agent.nodes import extractor as extractor_module
from src.agent.tools.mode_tools import ModeTool
from src.agent.utils.chatbot_utils import PromptUtils, PydanticUtils
from src.infrastructure.external.client.gpt_client import GPTClient
from src.schema.prewalk_schema import (
    CircularPreference,
    Location,
    OnewayPreference,
    OnewayShortestPreference,
    State,
)

# 후처리(_apply_postprocessing) 재현에는 UserPreference DB 조회가 필요할 수 있는데
# (예외9: 온보딩 기본 거리), 이 스크립트는 DB를 쓰지 않는다는 원칙을 유지하기 위해
# 항상 "온보딩 선호 거리 없음"으로 취급하도록 모킹한다.
extractor_module.UserPreferenceRepository.get_by_user_id = lambda user_id: None

# 후처리 재현용 고정 State 값. 실제 위치·사용자와 무관하며, "출발지 없으면 현재 위치로"
# 예외가 발동할 때만 쓰인다(이 30개 케이스는 대부분 origin이 있어 거의 안 쓰인다).
_EVAL_USER_ID = 0
_CURRENT_LOCATION = Location(lat=37.5665, lon=126.9780, address="서울 중구 세종대로 110", place_name="서울시청")

# State.user_context에 실리는 Preference의 mode(WalkMode) 값 -> tool 이름 대응.
# extraction.yaml [3]에 넣은 대응표와 동일한 소스(WalkMode)를 사용한다.
_MODE_TO_TOOL = {
    "circular_random":  "select_circular",
    "oneway_random":    "select_oneway",
    "oneway_shortest":  "select_oneway_shortest",
    "gps_art":          "select_gps_art",
    "waypoint":         "select_waypoint",
}

DONT_CARE = "*"  # expect 값에 쓰면 그 필드는 비교하지 않는다

# ── 검증 케이스 ──────────────────────────────────────────────────────────────
# expect 필드 의미:
#   tool         : 기대 도구 이름(select_circular / select_oneway / select_oneway_shortest).
#                  None이면 "도구를 호출하지 않아야 함"
#   origin       : 기대 place_name(부분 일치 허용) / None(비어 있어야 함) / "*"(비교 안 함)
#   destination  : origin과 동일 규칙
#   target_km    : 기대 숫자 / None(없어야 함) / "*"
#   target_minutes: target_km과 동일 규칙. 이번 발화가 시간(분/시간)으로만 새 거리를 말한
#                  경우에만 값을 기대한다 — km 환산(4km/h)은 Extractor.run()이 하므로 여기서는
#                  raw tool_call의 target_minutes 원본 숫자만 본다.
# context: [Current Context] 자리에 넣을 값. 생략(또는 None) 시 "없음".
#   실제 State.user_context와 같은 모양을 쓰기 위해 CircularPreference/OnewayPreference
#   등 prewalk_schema Pydantic 인스턴스를 그대로 넣는다(PromptUtils.format_for_prompt가
#   Pydantic·dict·문자열을 모두 받아 문자열로 변환한다).


def _loc(place_name: str) -> Location:
    """좌표 없이 place_name만 있는 위치(대화 중 아직 좌표 미확정 상태)."""
    return Location(place_name=place_name)


CASES: list[dict] = [

    # =========================================================================
    # 부분 수정(Rule 3): Current Context를 잘 "유지"하는가 (case_101~130, 30개)
    # 전부 context를 채운 상태에서 시작한다 — 목적은 "context 있음 vs 없음" 대조가
    # 아니라, context가 있을 때 (a) 언급 안 한 필드가 그대로 유지되는지 (b) 언급한
    # 필드만 정확히 바뀌는지 (c) 모드는 명시적으로 요구했을 때만 바뀌는지를 본다.
    # extraction.yaml의 few-shot 예시(잠실역→강남역 최단 / "오늘 뭐 먹지?" /
    # 수유역 순환+거리수정 / 미아사거리역→수유역 최단+장소수정 /
    # 철산역→광명사거리역 편도+다중필드수정)의 장소·문구와는 전부 겹치지 않게 썼다.
    # =========================================================================

    # A. 거리만 수정 (101~106)
    {
        "id": "case_101",
        "desc": "순환 context, 거리 증가",
        "context": CircularPreference(origin=_loc("봉천역"), target_km=3.0),
        "utterance": "오늘은 좀 더 걷고 싶어, 6km 정도로 해줘",
        "expect": {"tool": "select_circular", "origin": "봉천역", "target_km": 6.0},
    },
    {
        "id": "case_102",
        "desc": "순환 context, 거리 감소",
        "context": CircularPreference(origin=_loc("신림역"), target_km=5.0),
        "utterance": "아니다, 짧게 2km만 걸을래",
        "expect": {"tool": "select_circular", "origin": "신림역", "target_km": 2.0},
    },
    {
        "id": "case_103",
        "desc": "편도 우회 context, 거리 증가(장소는 그대로)",
        "context": OnewayPreference(origin=_loc("서울대입구역"), destination=_loc("사당역"), target_km=3.0),
        "utterance": "거리를 6km로 채워서 가줘",
        "expect": {"tool": "select_oneway", "origin": "서울대입구역", "destination": "사당역", "target_km": 6.0},
    },
    {
        "id": "case_104",
        "desc": "편도 우회 context, 거리 감소(장소는 그대로)",
        "context": OnewayPreference(origin=_loc("교대역"), destination=_loc("남부터미널역"), target_km=4.0),
        "utterance": "그냥 1.5km만 채우고 갈래",
        "expect": {"tool": "select_oneway", "origin": "교대역", "destination": "남부터미널역", "target_km": 1.5},
    },
    {
        "id": "case_105",
        "desc": "최단 context, 거리를 채워달라는 모순 요청 — target_km 필드 자체가 없는 모드",
        "context": OnewayShortestPreference(origin=_loc("용산역"), destination=_loc("이촌역")),
        "utterance": "그래도 5km 정도는 채워서 갔으면 좋겠어",
        # "최단"을 부정하거나 "우회"를 명시하지 않았으므로 Rule 3상 모드는 유지돼야 한다.
        # select_oneway_shortest에는 target_km 필드가 없어 이 요구는 반영될 자리가 없다.
        "expect": {"tool": "select_oneway_shortest", "origin": "용산역", "destination": "이촌역"},
    },
    {
        "id": "case_106",
        "desc": "순환 context, 시간(분) 단위로 새 거리 재요청 — 옛 km 대신 target_minutes로 채워야 함",
        "context": CircularPreference(origin=_loc("합정역"), target_km=3.0),
        "utterance": "이번엔 25분 정도만 걷고 싶어",
        # 시간 언급은 새 거리를 정하겠다는 뜻이므로 [Current Context]의 옛 target_km(3.0)을
        # 그대로 채우면 안 되고, target_minutes=25만 채워야 한다(km 환산은 Extractor.run()의
        # 파이썬 로직 — 이 eval 범위 밖).
        "expect": {"tool": "select_circular", "origin": "합정역", "target_km": None, "target_minutes": 25.0},
    },

    # B. 장소만 수정 (107~112)
    {
        "id": "case_107",
        "desc": "순환 context, 출발지만 수정",
        "context": CircularPreference(origin=_loc("노원역"), target_km=3.0),
        "utterance": "아 잠깐, 대림역 쪽에서 시작하고 싶어",
        "expect": {"tool": "select_circular", "origin": "대림역", "target_km": 3.0},
    },
    {
        "id": "case_108",
        "desc": "편도 우회 context, 목적지만 수정",
        "context": OnewayPreference(origin=_loc("구로디지털단지역"), destination=_loc("신도림역"), target_km=3.0),
        "utterance": "도착지를 영등포역으로 바꿔줘",
        "expect": {"tool": "select_oneway", "origin": "구로디지털단지역", "destination": "영등포역", "target_km": 3.0},
    },
    {
        "id": "case_109",
        "desc": "편도 우회 context, 출발지만 수정",
        "context": OnewayPreference(origin=_loc("여의나루역"), destination=_loc("당산역"), target_km=3.0),
        "utterance": "출발은 여의도역에서 할게",
        "expect": {"tool": "select_oneway", "origin": "여의도역", "destination": "당산역", "target_km": 3.0},
    },
    {
        "id": "case_110",
        "desc": "최단 context, 목적지만 수정",
        "context": OnewayShortestPreference(origin=_loc("성수역"), destination=_loc("뚝섬역")),
        "utterance": "목적지 건대입구역으로 바꿔줘",
        "expect": {"tool": "select_oneway_shortest", "origin": "성수역", "destination": "건대입구역"},
    },
    {
        "id": "case_111",
        "desc": "편도 우회 context, 출발·목적지 둘 다 수정, 거리는 유지",
        "context": OnewayPreference(origin=_loc("을지로입구역"), destination=_loc("종각역"), target_km=4.0),
        "utterance": "출발은 시청역에서, 도착은 광화문으로 할래",
        "expect": {"tool": "select_oneway", "origin": "시청역", "destination": "광화문", "target_km": 4.0},
    },
    {
        "id": "case_112",
        "desc": "순환 context, 출발지를 위치 대명사로 되돌림 — origin은 null이어야 함",
        "context": CircularPreference(origin=_loc("압구정로데오역"), target_km=3.0),
        "utterance": "아니다, 그냥 지금 있는 곳에서 할래",
        "expect": {"tool": "select_circular", "origin": None, "target_km": 3.0},
    },

    # C. 모드를 명시적으로 변경 (113~118) — 5개 모드 쌍 왕복
    {
        "id": "case_113",
        "desc": "순환 → 편도 우회 (목적지가 새로 생김, '편도'/'최단' 언급 없어 기본 select_oneway)",
        "context": CircularPreference(origin=_loc("청담동"), target_km=3.0),
        "utterance": "생각 바꿨어, 한남동까지 갈래",
        "expect": {"tool": "select_oneway", "origin": "청담동", "destination": "한남동", "target_km": 3.0},
    },
    {
        "id": "case_114",
        "desc": "편도 우회 → 최단 (명시적 '최단')",
        "context": OnewayPreference(origin=_loc("이태원역"), destination=_loc("한강진역"), target_km=3.0),
        "utterance": "이번엔 최단으로 가줘",
        "expect": {"tool": "select_oneway_shortest", "origin": "이태원역", "destination": "한강진역"},
    },
    {
        "id": "case_115",
        "desc": "최단 → 편도 우회 ('우회'+거리 명시로 target_km이 새로 생겨야 함)",
        "context": OnewayShortestPreference(origin=_loc("잠원한강공원"), destination=_loc("반포한강공원")),
        "utterance": "우회해서 3km 정도 채워서 가고 싶어",
        "expect": {"tool": "select_oneway", "origin": "잠원한강공원", "destination": "반포한강공원", "target_km": 3.0},
    },
    {
        "id": "case_116",
        "desc": "편도 우회 → 순환 (목적지 철회 명시)",
        "context": OnewayPreference(origin=_loc("노량진역"), destination=_loc("대방역"), target_km=3.0),
        "utterance": "목적지 없이 그냥 순환으로 돌고 싶어",
        "expect": {"tool": "select_circular", "origin": "노량진역", "target_km": 3.0},
    },
    {
        "id": "case_117",
        "desc": "최단 → 순환 (목적지 철회 명시, 거리·시간 미언급 — target_km은 비워둬야 함)",
        "context": OnewayShortestPreference(origin=_loc("신길역"), destination=_loc("영등포구청역")),
        "utterance": "정해진 도착지 없이 그냥 순환으로 해줘",
        # 최단 context엔 target_km이 없어 carryover할 값이 없고, 이번 발화도 거리·시간을
        # 언급하지 않았다. extraction.yaml이 "말하지 않으면 3.0"을 더 이상 지시하지 않으므로
        # (기본값은 Extractor.run()의 파이썬 로직이 채움 — 이 eval 범위 밖) None이 정답이다.
        "expect": {"tool": "select_circular", "origin": "신길역", "target_km": None},
    },
    {
        "id": "case_118",
        "desc": "순환 → 최단 (목적지+'최단' 동시 신규)",
        "context": CircularPreference(origin=_loc("성수동"), target_km=3.0),
        "utterance": "건대입구역까지 최단으로 가고 싶어졌어",
        "expect": {"tool": "select_oneway_shortest", "origin": "성수동", "destination": "건대입구역"},
    },

    # D. 무관한 대화·모호한 불만 — context 보존(=tool 미호출) 확인 (119~123)
    {
        "id": "case_119",
        "desc": "순환 context 중 무관한 잡담",
        "context": CircularPreference(origin=_loc("반포동"), target_km=3.0),
        "utterance": "나 지금 너무 배고파 죽겠다",
        "expect": {"tool": None},
    },
    {
        "id": "case_120",
        "desc": "편도 우회 context 중 막연한 불만(무엇을 바꿀지 특정 안 됨)",
        "context": OnewayPreference(origin=_loc("당산역"), destination=_loc("합정역"), target_km=3.0),
        "utterance": "음... 이거 말고 다른 느낌 없나",
        "expect": {"tool": None},
    },
    {
        "id": "case_121",
        "desc": "최단 context 중 막연한 재요청",
        "context": OnewayShortestPreference(origin=_loc("건대입구역"), destination=_loc("성수역")),
        "utterance": "다른 방법은 없어?",
        "expect": {"tool": None},
    },
    {
        "id": "case_122",
        "desc": "순환 context 중 날씨 잡담",
        "context": CircularPreference(origin=_loc("잠실나루역"), target_km=3.0),
        "utterance": "밖에 비 오려나?",
        "expect": {"tool": None},
    },
    {
        "id": "case_123",
        "desc": "편도 우회 context 중 인사말",
        "context": OnewayPreference(origin=_loc("영등포역"), destination=_loc("신도림역"), target_km=3.0),
        "utterance": "좋은 아침!",
        "expect": {"tool": None},
    },

    # E. 다중 필드 동시 수정 (124~127)
    {
        "id": "case_124",
        "desc": "편도 우회 context, 목적지+거리 동시 수정",
        "context": OnewayPreference(origin=_loc("삼각지역"), destination=_loc("숙대입구역"), target_km=3.0),
        "utterance": "도착지는 서울역으로, 거리는 5km로 바꿔줘",
        "expect": {"tool": "select_oneway", "origin": "삼각지역", "destination": "서울역", "target_km": 5.0},
    },
    {
        "id": "case_125",
        "desc": "순환 context, 출발지+거리 동시 수정",
        "context": CircularPreference(origin=_loc("한남동"), target_km=3.0),
        "utterance": "출발지 옥수역으로 바꾸고, 4km로 늘려줘",
        "expect": {"tool": "select_circular", "origin": "옥수역", "target_km": 4.0},
    },
    {
        "id": "case_126",
        "desc": "최단 context, 출발지+목적지 동시 수정",
        "context": OnewayShortestPreference(origin=_loc("종로3가역"), destination=_loc("동대문역")),
        "utterance": "출발은 안국역에서, 도착은 혜화역으로 바꿔줘",
        "expect": {"tool": "select_oneway_shortest", "origin": "안국역", "destination": "혜화역"},
    },
    {
        "id": "case_127",
        "desc": "편도 우회 context, 출발·목적지·거리 전부 수정(모드 언급은 없음)",
        "context": OnewayPreference(origin=_loc("당산역"), destination=_loc("영등포구청역"), target_km=3.0),
        "utterance": "출발은 문래역, 도착은 신도림역, 거리는 4.5km로 다 바꿔줘",
        "expect": {"tool": "select_oneway", "origin": "문래역", "destination": "신도림역", "target_km": 4.5},
    },

    # F. 동일 값 재언급·테마만 언급 — 불필요하게 값이 흔들리지 않는지 (128~130)
    {
        "id": "case_128",
        "desc": "편도 우회 context, 같은 출발지를 다시 언급 — 값이 그대로 유지돼야 함",
        "context": OnewayPreference(origin=_loc("홍대입구역"), destination=_loc("합정역"), target_km=3.0),
        "utterance": "역시 홍대입구역에서 다시 시작할래",
        "expect": {"tool": "select_oneway", "origin": "홍대입구역", "destination": "합정역", "target_km": 3.0},
    },
    {
        "id": "case_129",
        "desc": "순환 context, 같은 거리를 다시 확인 — 값이 그대로 유지돼야 함",
        "context": CircularPreference(origin=_loc("여의도공원"), target_km=3.0),
        "utterance": "음, 역시 3km가 딱 좋겠다",
        "expect": {"tool": "select_circular", "origin": "여의도공원", "target_km": 3.0},
    },
    {
        "id": "case_130",
        "desc": "편도 우회 context, 테마만 언급(장소·거리 미언급) — 모드·필드 전부 유지돼야 함",
        "context": OnewayPreference(origin=_loc("대림역"), destination=_loc("구로디지털단지역"), target_km=3.0),
        "utterance": "좀 더 조용한 길로 가고 싶어",
        "expect": {"tool": "select_oneway", "origin": "대림역", "destination": "구로디지털단지역", "target_km": 3.0},
    },
]

# ── 비교 유틸 ────────────────────────────────────────────────────────────────
def _name_of(value) -> str | None:
    """tool_call 인자에서 place_name을 뽑는다(dict / bare str / None 모두 처리)."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get("place_name")
    if isinstance(value, str):
        return value or None
    return None


def _loc_match(expected, actual_arg) -> bool:
    name = _name_of(actual_arg)
    if expected is None:
        return name is None
    if expected == DONT_CARE:
        return True
    if name is None:
        return False
    e, a = str(expected).replace(" ", ""), str(name).replace(" ", "")
    return e in a or a in e


def _num_match(expected, actual) -> bool:
    if expected == DONT_CARE:
        return True
    if expected is None:
        return actual is None
    if actual is None:
        return False
    return abs(float(actual) - float(expected)) < 1e-6


def evaluate(case: dict, tool_name: str | None, args: dict) -> list[str]:
    """케이스 기대값과 실제 tool_call을 대조해 실패 사유 리스트를 반환(빈 리스트면 통과)."""
    expect = case["expect"]
    fails: list[str] = []

    if expect["tool"] is None:
        if tool_name is not None:
            fails.append(f"도구 호출 없어야 하는데 {tool_name} 호출됨")
        return fails

    if tool_name != expect["tool"]:
        fails.append(f"tool: 기대 {expect['tool']} / 실제 {tool_name}")
        return fails  # 도구가 틀리면 필드 비교는 무의미

    if "origin" in expect and not _loc_match(expect["origin"], args.get("origin")):
        fails.append(f"origin: 기대 {expect['origin']!r} / 실제 {_name_of(args.get('origin'))!r}")
    if "destination" in expect and not _loc_match(expect["destination"], args.get("destination")):
        fails.append(
            f"destination: 기대 {expect['destination']!r} / 실제 {_name_of(args.get('destination'))!r}"
        )
    if "target_km" in expect and not _num_match(expect["target_km"], args.get("target_km")):
        fails.append(f"target_km: 기대 {expect['target_km']} / 실제 {args.get('target_km')}")
    if "target_minutes" in expect and not _num_match(expect["target_minutes"], args.get("target_minutes")):
        fails.append(f"target_minutes: 기대 {expect['target_minutes']} / 실제 {args.get('target_minutes')}")

    if "min_target_km" in case:
        tk = args.get("target_km")
        if tk is None or float(tk) < case["min_target_km"]:
            fails.append(f"target_km: {case['min_target_km']} 이상이어야 하는데 {tk}")

    return fails


def _context_summary(context) -> str | None:
    """
    case["context"]를 사람이 콘솔에서 바로 읽을 수 있는 한 줄 JSON으로 요약한다.
    PromptUtils.format_for_prompt()는 LangChain 템플릿용으로 중괄호를 {{, }}로
    이스케이프하고 여러 줄로 들여쓰기 때문에 로그 출력용으로는 그대로 쓰지 않는다.
    context가 없으면(None) None을 반환해 호출부가 아예 줄을 안 찍게 한다.
    """
    if context is None:
        return None
    return json.dumps(PydanticUtils.dump(context), ensure_ascii=False)


# ── 실행 ────────────────────────────────────────────────────────────────────
async def _one_call(client: GPTClient, model, utterance: str, context) -> tuple[str | None, dict]:
    current_context = PromptUtils().format_for_prompt(context)
    res = await client.get_response(
        prompt_name="extraction",
        input_variables={"user_input": utterance, "current_context": current_context},
        llm=model,
    )
    calls = getattr(res, "tool_calls", None) or []
    if not calls:
        return None, {}
    return calls[0]["name"], calls[0].get("args", {}) or {}


def _post_process(extractor: Extractor, tool_name: str | None, raw_args: dict, case: dict) -> tuple[str | None, dict]:
    """
    _one_call()이 낸 raw tool_call(tool_name, raw_args)에 Extractor._apply_postprocessing()
    (예외3~10)을 그대로 적용해 최종 결과를 재현한다. LLM을 다시 부르지 않는다 — 같은 raw
    tool_call을 그대로 후처리하는 것이지, 독립적으로 다시 추출한 결과가 아니다(두 번 호출하면
    temperature=0.1이라도 다른 tool_call이 나올 수 있어 "전/후" 비교가 깨진다).
    tool 미호출(raw tool_name=None)이면 후처리할 것도 없으므로 그대로 (None, {})를 반환한다.
    """
    if tool_name is None:
        return None, {}

    state = State(
        user_id=_EVAL_USER_ID,
        current_location=_CURRENT_LOCATION,
        user_context=case.get("context"),
        user_prompt=case["utterance"],
    )
    pref = extractor._apply_postprocessing(tool_name, dict(raw_args), state)
    if pref is None:
        return None, {}
    post_tool = _MODE_TO_TOOL.get(pref.mode.value, pref.mode.value)
    return post_tool, pref.model_dump()


async def run(args: argparse.Namespace) -> int:
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY가 없습니다(.env 확인).")
        return 2

    cases = CASES
    if args.only:
        wanted = {c.strip() for c in args.only.split(",")}
        cases = [c for c in CASES if c["id"] in wanted]
        missing = wanted - {c["id"] for c in cases}
        if missing:
            print(f"알 수 없는 케이스 id: {sorted(missing)}")
            return 2

    client = GPTClient()
    if args.model or args.temperature is not None:
        client.llm = ChatOpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            model=args.model or "gpt-4o-mini",
            temperature=args.temperature if args.temperature is not None else 0.1,
        )
    model = client.llm.bind_tools(ModeTool().tools)
    extractor = Extractor()  # 후처리(예외3~10) 재현용. LLM은 아래에서 client/model로 직접 호출한다.

    print(f"extraction.yaml eval | model={client.llm.model_name} "
          f"temperature={client.llm.temperature} repeat={args.repeat} cases={len(cases)}")
    print("=" * 78)

    passed = failed = 0
    post_passed = post_failed = 0
    for case in cases:
        # 각 실행: raw tool_call과, 그 raw 결과를 후처리(예외3~10)한 결과를 한 쌍으로 묶는다.
        # 후처리는 raw tool_call을 그대로 재사용하지 새 LLM 호출을 만들지 않는다 — 그래야
        # "같은 추출 결과의 전/후"를 비교하는 게 된다(독립적으로 두 번 추출한 결과가 아님).
        runs: list[tuple] = []
        for _ in range(args.repeat):
            tool_name, call_args = await _one_call(
                client, model, case["utterance"], case.get("context")
            )
            post_tool, post_args = _post_process(extractor, tool_name, call_args, case)
            runs.append((
                tool_name, call_args, evaluate(case, tool_name, call_args),
                post_tool, post_args, evaluate(case, post_tool, post_args),
            ))

        ok_runs = sum(1 for _, _, f, *_ in runs if not f)
        is_pass = ok_runs == args.repeat
        passed += is_pass
        failed += not is_pass

        post_ok_runs = sum(1 for *_, pf in runs if not pf)
        post_is_pass = post_ok_runs == args.repeat
        post_passed += post_is_pass
        post_failed += not post_is_pass

        tag = "PASS" if is_pass else ("FLAKY" if 0 < ok_runs < args.repeat else "FAIL")
        post_tag = "PASS" if post_is_pass else ("FLAKY" if 0 < post_ok_runs < args.repeat else "FAIL")
        consist = f" ({ok_runs}/{args.repeat})" if args.repeat > 1 else ""
        post_consist = f" ({post_ok_runs}/{args.repeat})" if args.repeat > 1 else ""
        print(f"[raw {tag}{consist} / 후처리 {post_tag}{post_consist}] {case['id']} — {case['desc']}")
        ctx_str = _context_summary(case.get("context"))
        if ctx_str is not None:
            print(f"       context: {ctx_str}")
        print(f"       발화: {case['utterance']}")

        # 매 케이스마다 실제로 호출된 도구(모드)를 raw/후처리 각각 출력한다.
        called = Counter("(호출 없음)" if t is None else t for t, *_ in runs)
        called_str = ", ".join(
            f"{name} ×{n}" if args.repeat > 1 else name for name, n in called.most_common()
        )
        post_called = Counter("(호출 없음)" if pt is None else pt for *_, pt, _, _ in runs)
        post_called_str = ", ".join(
            f"{name} ×{n}" if args.repeat > 1 else name for name, n in post_called.most_common()
        )
        expected_str = case["expect"]["tool"] or "(호출 없음)"
        print(f"       호출(raw)  : {called_str}   (기대: {expected_str})")
        print(f"       호출(후처리): {post_called_str}   (기대: {expected_str})")

        if not is_pass or not post_is_pass or args.verbose:
            seen: set[str] = set()
            for tool_name, call_args, fails, post_tool, post_args, post_fails in runs:
                sig = f"{tool_name}|{fails}|{post_tool}|{post_fails}"
                if sig in seen and not args.verbose:
                    continue
                seen.add(sig)
                print(f"       → raw    : tool={tool_name} args={call_args}")
                for f in fails:
                    print(f"         ✗ {f}")
                print(f"       → 후처리 : tool={post_tool} args={post_args}")
                for f in post_fails:
                    print(f"         ✗ {f}")
        print()

    print("=" * 78)
    print(f"결과(raw)  : {passed} PASS / {failed} FAIL  (총 {len(cases)})")
    print(f"결과(후처리): {post_passed} PASS / {post_failed} FAIL  (총 {len(cases)})")
    return 1 if failed else 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="extraction.yaml 프롬프트 검증")
    p.add_argument("--repeat", type=int, default=1, help="케이스별 반복 호출 수(비결정성 확인)")
    p.add_argument("--only", type=str, default="", help="쉼표로 구분한 케이스 id만 실행")
    p.add_argument("--model", type=str, default="", help="모델 override (기본: gpt-4o-mini)")
    p.add_argument("--temperature", type=float, default=None, help="temperature override")
    p.add_argument("--verbose", action="store_true", help="통과 케이스도 tool_call 상세 출력")
    return p.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parse_args())))
