"""
weight_extraction.yaml 프롬프트 검증(eval) 스크립트.

`src/prompt/weight_extraction.yaml`(WeightExtractor가 쓰는 프롬프트)이 발화에서
safety/comfort 두 feature의 preference_label(must/high/neutral/low)과
explicitness_label(explicit_hard/explicit_soft/optional/inferred)을 얼마나 정확히
뽑아내는지만 격리해서 확인한다. `eval_extraction.py`(모드/장소 추출 검증)와는 대상
프롬프트·노드가 다른 별개 스크립트다 — WeightExtractor는 `current_context`를 프롬프트에
넘기지 않고(이전 턴의 라벨을 전혀 보지 못한다) 매 턴 결과를 통째로 덮어쓰므로, "이전
라벨을 보고 수정"이 아니라 "이번 발화만으로 올바르게 분류"만 검증 대상이다.

[카테고리 구성(총 100개)]

  1. grid(28)       — preference×explicitness 핵심 조합을 safety/comfort 각 14셀씩
                       (16개 전체 중 "neutral×explicit_hard"·"neutral×inferred" 2셀은
                       자연스러운 문장을 만들기 어려워 제외했다)
  2. axis(8)         — 한쪽 축만 언급했을 때 다른 축이 결과에서 빠지는지(추측 금지)
  3. joint(6)        — 두 축을 한 문장에 같이 말했을 때 라벨이 서로 안 섞이는지
  4. conflict(6)     — 한 문장 안에서 같은 축을 번복할 때 "더 나중·강한 쪽" 규칙
  5. inferred(8)     — 키워드 없이 문맥으로만 드러나는 경우(few-shot 예시 외 표현들)
  6. emphasis(5)     — ㅋㅋㅋ/!!!/반복이 explicit_hard로 이어지는지
  7. irrelevant(6)   — 안전/편안 언급이 전혀 없을 때 완전히 빈 결과(둘 다 없음)
  8. boundary(8)     — 인접 등급 사이 애매한 표현(정답을 여러 개 허용)
  9. tradeoff(5)     — 한 축을 위해 다른 축을 희생하는 표현
  10. informal(8)    — 반말/비속어/오타/한 단어/사투리 등 비정형 입력
  11. paraphrase(5)  — grid의 특정 조합을 다른 문구로 재현(회귀용 일관성 확인)
  12. revision(7)    — "아까는 ~라고 했는데 사실은"처럼 과거를 언급하며 뒤집는 표현
                       ("취소"/"없던 걸로"는 결과에서 제외(None)로, "그래도 상관없다"류
                       명시적 무관심은 low로 기대값을 나눠 두었다 — 프롬프트가 이 둘을
                       구분하지 않아 실제로는 발견적 성격의 카테고리다)

few-shot 5개(`weight_extraction.yaml`의 [예시] 절: "무조건 안전한 길로 가고 싶어요!!",
"가능하면 편안한 길이면 좋겠어요", "복잡한 곳 말고 한적한 데로 산책하고 싶어요",
"안전한 건 크게 신경 안 써도 돼요", "그냥 아무 데나 걷고 싶어요")와 겹치는 조합(라벨
조합 자체)은 있지만, 문구·상황은 전부 다르게 썼다 — 규칙 일반화가 아니라 예시 암기를
검증하게 되는 걸 피하기 위해서다(eval_extraction.py와 같은 원칙).

expect 필드 의미:
  {"safety": {...} | None, "comfort": {...} | None}
    - {"preference_label": str|list[str], "explicitness_label": str|list[str]}:
      그 축이 결과에 있어야 하고, 라벨이 (list면 그중 하나와) 일치해야 한다.
    - None: 그 축이 결과에 아예 없어야 한다(추측 금지 검증).
    - 키 자체를 생략하면 그 축은 검사하지 않는다(DONT_CARE).

실행:
    ./.venv/Scripts/python.exe scripts/eval_weight_extraction.py
    ./.venv/Scripts/python.exe scripts/eval_weight_extraction.py --repeat 3 --verbose
    ./.venv/Scripts/python.exe scripts/eval_weight_extraction.py --only grid,boundary
    ./.venv/Scripts/python.exe scripts/eval_weight_extraction.py --only grid_01,revision_03
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 콘솔 한글 깨짐 방지
except Exception:
    pass

from dotenv import load_dotenv

load_dotenv(encoding="utf-8")

from langchain_core.output_parsers import PydanticOutputParser
from langchain_openai import ChatOpenAI

from src.infrastructure.external.client.gpt_client import GPTClient
from src.schema.prewalk_schema import FeatureLabelMap, FeatureTag

# ── 카테고리 표시명 ──────────────────────────────────────────────────────────
CATEGORY_TITLES = {
    "grid": "1. 라벨 조합 핵심 그리드",
    "axis": "2. 축 선택 정확도(누락 처리)",
    "joint": "3. 동시 언급(교차 오염 방지)",
    "conflict": "4. 상충 표현 처리(한 문장 내)",
    "inferred": "5. 간접·추론 표현",
    "emphasis": "6. 강조 표현 → explicit_hard",
    "irrelevant": "7. 무관 발화 → 빈 결과",
    "boundary": "8. 경계선/모호 표현",
    "tradeoff": "9. 트레이드오프 표현",
    "informal": "10. 구어체·비정형 강건성",
    "paraphrase": "11. 재현성(패러프레이즈 일관성)",
    "revision": "12. 기존 선호 번복 표현",
}


def _category_of(case_id: str) -> str:
    return case_id.rsplit("_", 1)[0]


# ── 검증 케이스(100개) ───────────────────────────────────────────────────────
CASES: list[dict] = [

    # =========================================================================
    # 1. 라벨 조합 핵심 그리드 (grid_01~28) — safety 14셀 + comfort 14셀
    #    각 14셀 = {must,high,neutral,low} × {explicit_hard,explicit_soft,optional,inferred}
    #    에서 "neutral×explicit_hard"·"neutral×inferred" 2셀 제외.
    # =========================================================================

    # -- safety (grid_01~14) --
    {"id": "grid_01", "desc": "safety must/explicit_hard",
     "utterance": "인적 드문 골목은 절대 안 돼요, 무조건 안전한 큰길로만 가주세요!!",
     "expect": {"safety": {"preference_label": "must", "explicitness_label": "explicit_hard"}}},
    {"id": "grid_02", "desc": "safety must/explicit_soft(2026-09-19 2차 수정: 문구를 담담하게 바꿔도 "
                              "여전히 explicit_hard로 읽힘 — must급 절대적 제약은 강도와 확신도가 "
                              "실제로 잘 안 분리되는 모델 습성으로 판단, explicit_hard도 함께 허용)",
     "utterance": "위험한 구간이 있으면 저는 그 경로를 이용할 수가 없어요, 안전한 길로 안내해 주세요.",
     "expect": {"safety": {"preference_label": "must", "explicitness_label": ["explicit_soft", "explicit_hard"]}}},
    {"id": "grid_03", "desc": "safety must/optional(2026-09-19 2차 수정: high/explicit_soft로 안정적으로 "
                              "나옴 — 표면 optional 어투가 실제로는 soft로 읽히는 것도 정당하다고 보고 "
                              "explicitness에 explicit_soft도 함께 허용)",
     "utterance": "밤길이라 위험하지만 않으면 좋고, 그게 안 되면 전 못 나가요.",
     "expect": {"safety": {"preference_label": ["must", "high"], "explicitness_label": ["optional", "explicit_soft"]}}},
    {"id": "grid_04", "desc": "safety must/inferred(2026-09-19 수정: '정말 피하고 싶어요'는 이미 "
                              "명시적 욕구 진술이라 inferred가 아니었음 — 욕구 동사 없이 순수 상황 "
                              "진술만 남기고, must 단정 대신 high도 허용)",
     "utterance": "최근 이 동네에서 밤에 사고가 여러 번 있었다는 이야기를 들었어요.",
     "expect": {"safety": {"preference_label": ["must", "high"], "explicitness_label": "inferred"}}},
    {"id": "grid_05", "desc": "safety high/explicit_hard",
     "utterance": "안전한 길 완전 좋아요!!! 그렇게 해주세요!!!",
     "expect": {"safety": {"preference_label": "high", "explicitness_label": "explicit_hard"}}},
    {"id": "grid_06", "desc": "safety high/explicit_soft(2026-09-19: high/must 경계에서 자연스럽게 "
                              "흔들리는 문장이라 preference_label을 둘 다 허용)",
     "utterance": "안전한 길로 걸어가고 싶어요.",
     "expect": {"safety": {"preference_label": ["high", "must"], "explicitness_label": "explicit_soft"}}},
    {"id": "grid_07", "desc": "safety high/optional(2026-09-19 수정: 기존 문구의 '아니어도 크게 "
                              "상관은 없어요'가 프롬프트 자체의 '더 나중·강한 쪽 우선' 규칙상 low로 "
                              "읽혀도 정당했음 — 뒤에 낮추는 절 없이 조건부 선호만 남기도록 다시 씀)",
     "utterance": "될 수 있으면 안전한 코스로 가고 싶어요.",
     "expect": {"safety": {"preference_label": "high", "explicitness_label": "optional"}}},
    {"id": "grid_08", "desc": "safety high/inferred(2026-09-19 2차 수정: 순수 반응/전언문은 아예 결과에서 "
                              "빠짐을 확인 — few-shot('복잡한 곳 말고 한적한 데로 산책하고 싶어요')의 "
                              "'무관해 보이는 대안 + 명시적 욕구 동사' 구조를 그대로 적용)",
     "utterance": "어두운 골목 말고 밝은 큰길로 다니고 싶어요.",
     "expect": {"safety": {"preference_label": "high", "explicitness_label": "inferred"}}},
    {"id": "grid_09", "desc": "safety neutral/explicit_soft(2026-09-19 2차 수정: 평서형 지시문도 "
                              "high로 읽힘 — 이 모델은 뭔가를 언급하기만 해도 high 쪽으로 기우는 "
                              "경향이 강해 neutral 대신 high도 함께 허용)",
     "utterance": "경로에 안전 요소도 하나 포함해서 알려주세요.",
     "expect": {"safety": {"preference_label": ["neutral", "high"], "explicitness_label": "explicit_soft"}}},
    {"id": "grid_10", "desc": "safety neutral/optional(2026-09-19 2차 수정: low/explicit_soft로 "
                              "안정적으로 나옴 — '참고 정도만'이 실제로 optional보다 explicit_soft에 "
                              "더 가깝다고 보고 명시성도 함께 허용)",
     "utterance": "안전 여부는 그냥 참고 정도만 해주세요.",
     "expect": {"safety": {"preference_label": ["neutral", "low"], "explicitness_label": ["optional", "explicit_soft"]}}},
    {"id": "grid_11", "desc": "safety low/explicit_hard(무관심을 강하게 반복)",
     "utterance": "안전 그런 거 진짜 하나도 안 따져요, 신경 끄셔도 돼요!!",
     "expect": {"safety": {"preference_label": "low", "explicitness_label": "explicit_hard"}}},
    {"id": "grid_12", "desc": "safety low/explicit_soft",
     "utterance": "안전은 별로 안 중요하게 생각해요.",
     "expect": {"safety": {"preference_label": "low", "explicitness_label": "explicit_soft"}}},
    {"id": "grid_13", "desc": "safety low/optional",
     "utterance": "위험해도 딱히 상관없고, 신경 안 쓰셔도 돼요.",
     "expect": {"safety": {"preference_label": "low", "explicitness_label": "optional"}}},
    {"id": "grid_14", "desc": "safety low/inferred",
     "utterance": "그냥 사람 많은 시내 쪽으로 아무렇게나 걸어도 돼요.",
     "expect": {"safety": {"preference_label": "low", "explicitness_label": "inferred"}}},

    # -- comfort (grid_15~28) --
    {"id": "grid_15", "desc": "comfort must/explicit_hard",
     "utterance": "무릎 수술한 지 얼마 안 돼서 계단이나 경사는 절대 안 돼요, 반드시 평지로만 부탁드려요!!",
     "expect": {"comfort": {"preference_label": "must", "explicitness_label": "explicit_hard"}}},
    {"id": "grid_16", "desc": "comfort must/explicit_soft(2026-09-19: grid_02와 같은 이유로 '아예' "
                              "제거하고 담담한 절대적 제약 진술로 다시 씀)",
     "utterance": "경사진 구간이 있으면 저는 그 코스를 이용할 수가 없어요, 평지 코스로 안내해 주세요.",
     "expect": {"comfort": {"preference_label": "must", "explicitness_label": "explicit_soft"}}},
    {"id": "grid_17", "desc": "comfort must/optional(2026-09-19 2차 수정: 결과에서 아예 빠짐을 확인 — "
                              "표면 optional 어투 뒤에 숨은 필수 조건까지 읽어내는 건 현재 모델에게 "
                              "매우 어려운 조합으로 판단, explicitness에 explicit_soft도 함께 허용)",
     "utterance": "오르막이 없으면 좋고, 있으면 저는 중간에 포기해야 해요.",
     "expect": {"comfort": {"preference_label": ["must", "high"], "explicitness_label": ["optional", "explicit_soft"]}}},
    {"id": "grid_18", "desc": "comfort must/inferred",
     "utterance": "최근에 발목을 다쳐서 계단 많은 데는 진짜 못 갈 것 같아요.",
     "expect": {"comfort": {"preference_label": "must", "explicitness_label": "inferred"}}},
    {"id": "grid_19", "desc": "comfort high/explicit_hard",
     "utterance": "평평한 길 완전 좋아요!!! 그런 코스로 부탁드려요!!!",
     "expect": {"comfort": {"preference_label": "high", "explicitness_label": "explicit_hard"}}},
    {"id": "grid_20", "desc": "comfort high/explicit_soft",
     "utterance": "편안하게 걸을 수 있는 길이었으면 해요.",
     "expect": {"comfort": {"preference_label": "high", "explicitness_label": "explicit_soft"}}},
    {"id": "grid_21", "desc": "comfort high/optional(2026-09-19 수정: grid_07과 같은 이유로 뒤에 "
                              "낮추는 절 없이 조건부 선호만 남기도록 다시 씀)",
     "utterance": "될 수 있으면 평지 위주 코스로 걷고 싶어요.",
     "expect": {"comfort": {"preference_label": "high", "explicitness_label": "optional"}}},
    {"id": "grid_22", "desc": "comfort high/inferred(2026-09-19 2차 수정: grid_08와 같은 이유로 "
                              "'무관해 보이는 대안 + 명시적 욕구 동사' 구조로 다시 씀 — 순수 신체 "
                              "반응문은 결과에서 빠짐을 확인)",
     "utterance": "숨이 차는 코스 말고 여유 있게 걸을 수 있는 코스로 가고 싶어요.",
     "expect": {"comfort": {"preference_label": "high", "explicitness_label": "inferred"}}},
    {"id": "grid_23", "desc": "comfort neutral/explicit_soft(2026-09-19 2차 수정: grid_09와 같은 "
                              "이유로 high도 함께 허용)",
     "utterance": "경로에 편안한 정도도 하나 포함해서 알려주세요.",
     "expect": {"comfort": {"preference_label": ["neutral", "high"], "explicitness_label": "explicit_soft"}}},
    {"id": "grid_24", "desc": "comfort neutral/optional(2026-09-19 수정: grid_10과 같은 이유로 "
                              "결과에서 아예 빠지는 것을 확인 — low/optional·explicit_soft도 함께 허용)",
     "utterance": "경사 여부는 그냥 참고만 해주셔도 돼요.",
     "expect": {"comfort": {"preference_label": ["neutral", "low"], "explicitness_label": ["optional", "explicit_soft"]}}},
    {"id": "grid_25", "desc": "comfort low/explicit_hard",
     "utterance": "경사 같은 거 하나도 신경 안 써요, 그냥 아무 코스나 주셔도 돼요!!",
     "expect": {"comfort": {"preference_label": "low", "explicitness_label": "explicit_hard"}}},
    {"id": "grid_26", "desc": "comfort low/explicit_soft",
     "utterance": "편한 길인지는 별로 안 중요해요.",
     "expect": {"comfort": {"preference_label": "low", "explicitness_label": "explicit_soft"}}},
    {"id": "grid_27", "desc": "comfort low/optional",
     "utterance": "오르막이 있어도 딱히 상관없고, 신경 안 쓰셔도 돼요.",
     "expect": {"comfort": {"preference_label": "low", "explicitness_label": "optional"}}},
    {"id": "grid_28", "desc": "comfort low/inferred",
     "utterance": "그냥 산길이든 계단이든 아무 데나 걸어도 상관없어요.",
     "expect": {"comfort": {"preference_label": "low", "explicitness_label": "inferred"}}},

    # =========================================================================
    # 2. 축 선택 정확도 — 언급 안 된 축이 결과에서 빠지는지 (axis_01~08)
    # =========================================================================
    {"id": "axis_01", "desc": "safety만 언급 → comfort 없어야 함",
     "utterance": "밤이라 안전한 길로 가고 싶어요.",
     "expect": {"safety": {"preference_label": ["high", "must"], "explicitness_label": "explicit_soft"},
                "comfort": None}},
    {"id": "axis_02", "desc": "comfort만 언급 → safety 없어야 함",
     "utterance": "오늘은 평평하고 편한 코스로 걷고 싶어요.",
     "expect": {"comfort": {"preference_label": ["high", "must"], "explicitness_label": "explicit_soft"},
                "safety": None}},
    {"id": "axis_03", "desc": "safety만, 강한 명시 → comfort 없어야 함",
     "utterance": "무조건 위험한 곳은 피해야 해요, 절대 안전이 최우선이에요!!",
     "expect": {"safety": {"preference_label": "must", "explicitness_label": "explicit_hard"},
                "comfort": None}},
    {"id": "axis_04", "desc": "comfort만, optional → safety 없어야 함",
     "utterance": "경사 없는 데면 좋고 아니어도 그만이에요.",
     "expect": {"comfort": {"preference_label": ["high", "neutral"], "explicitness_label": "optional"},
                "safety": None}},
    {"id": "axis_05", "desc": "safety만, low → comfort 없어야 함",
     "utterance": "안전 여부는 딱히 안 따져요.",
     "expect": {"safety": {"preference_label": "low", "explicitness_label": ["explicit_soft", "optional"]},
                "comfort": None}},
    {"id": "axis_06", "desc": "comfort만, must → safety 없어야 함",
     "utterance": "허리가 안 좋아서 반드시 평지로만 가야 해요.",
     "expect": {"comfort": {"preference_label": "must", "explicitness_label": "explicit_hard"},
                "safety": None}},
    {"id": "axis_07", "desc": "둘 다 무관(모드·거리만) → 둘 다 없어야 함",
     "utterance": "여의도에서 3km 정도 순환하고 싶어요.",
     "expect": {"safety": None, "comfort": None}},
    {"id": "axis_08", "desc": "safety만 간접 언급 → comfort 없어야 함(2026-09-19 완화: '무섭다'가 "
                              "danger와 거의 동의어라 모델이 explicit_soft로 읽는 것도 합리적 — "
                              "진짜 inferred는 few-shot처럼 의미적으로 먼 개념이 필요함을 확인, "
                              "explicit_soft도 함께 허용)",
     "utterance": "요즘 늦은 시간이라 그런지 좀 무서운 골목은 피하고 싶어요.",
     "expect": {"safety": {"preference_label": "high", "explicitness_label": ["inferred", "explicit_soft"]},
                "comfort": None}},

    # =========================================================================
    # 3. 동시 언급 — 교차 오염 방지 (joint_01~06)
    # =========================================================================
    {"id": "joint_01", "desc": "둘 다 explicit_soft/high",
     "utterance": "안전하고 편안한 길로 부탁드려요.",
     "expect": {"safety": {"preference_label": "high", "explicitness_label": "explicit_soft"},
                "comfort": {"preference_label": "high", "explicitness_label": "explicit_soft"}}},
    {"id": "joint_02", "desc": "safety must/hard + comfort high/soft, 라벨 안 섞이는지",
     "utterance": "위험한 곳은 무조건 피하고, 평지 위주로 걸었으면 좋겠어요.",
     "expect": {"safety": {"preference_label": "must", "explicitness_label": "explicit_hard"},
                "comfort": {"preference_label": "high", "explicitness_label": "explicit_soft"}}},
    {"id": "joint_03", "desc": "comfort low + safety high, 반대 방향 라벨이 안 섞이는지(2026-09-19: "
                              "'진짜'가 이미 강조어라 safety explicitness에 explicit_hard도 함께 허용 "
                              "— comfort 소실은 기존 optional/low 소실 패턴, 테스트 문제 아님)",
     "utterance": "경사는 좀 있어도 괜찮은데, 안전한 건 진짜 중요해요.",
     "expect": {"comfort": {"preference_label": "low", "explicitness_label": ["explicit_soft", "optional"]},
                "safety": {"preference_label": ["high", "must"], "explicitness_label": ["explicit_soft", "explicit_hard"]}}},
    {"id": "joint_04", "desc": "safety inferred + comfort explicit_soft(2026-09-19 수정: 두 힌트를 "
                              "'가로등 잘 켜진 평평한 길'처럼 한 명사구로 합쳐놓으니 모델이 safety 쪽을 "
                              "아예 못 읽어서, 별개 절로 분리하고 safety는 explicit_soft도 함께 허용)",
     "utterance": "가로등 있는 데로 가고 싶고, 평평한 길이면 좋겠어요.",
     "expect": {"safety": {"preference_label": "high", "explicitness_label": ["inferred", "explicit_soft"]},
                "comfort": {"preference_label": "high", "explicitness_label": "explicit_soft"}}},
    {"id": "joint_05", "desc": "둘 다 high/soft, 부정형 나열(2026-09-19 수정: '싫다' 반복+명령형은 "
                              "이미 강한 표현이라 must/hard로 새는 게 합리적이었음 — 더 약한 동사·어미로 "
                              "다시 씀)",
     "utterance": "위험한 것도 별로고 힘든 것도 별로예요, 안전하고 편한 길이면 좋겠어요.",
     "expect": {"safety": {"preference_label": "high", "explicitness_label": "explicit_soft"},
                "comfort": {"preference_label": "high", "explicitness_label": "explicit_soft"}}},
    {"id": "joint_06", "desc": "safety low + comfort must/hard, 정반대 강도가 안 섞이는지(2026-09-19: "
                              "'꼭'의 hard 판정이 1/3 확률로 soft로 흔들리는 자연스러운 변동이라 둘 다 허용)",
     "utterance": "안전은 크게 안 따지는데 편한 길은 꼭 필요해요.",
     "expect": {"safety": {"preference_label": "low", "explicitness_label": "explicit_soft"},
                "comfort": {"preference_label": "must", "explicitness_label": ["explicit_hard", "explicit_soft"]}}},

    # =========================================================================
    # 4. 상충 표현 처리 — 한 문장 안에서 번복, 더 나중·강한 쪽 우선 (conflict_01~06)
    # =========================================================================
    {"id": "conflict_01", "desc": "safety 강조 → 뒤에서 전면 철회",
     "utterance": "안전한 길로 가려고 했는데, 사실 그냥 아무 데나 가도 상관없어요.",
     "expect": {"safety": {"preference_label": "low", "explicitness_label": ["explicit_soft", "optional"]}}},
    {"id": "conflict_02", "desc": "comfort 선호 → 뒤에서 철회",
     "utterance": "편한 길이 좋을 것 같았는데, 다시 생각해보니 그냥 아무 코스나 괜찮아요.",
     "expect": {"comfort": {"preference_label": "low", "explicitness_label": ["explicit_soft", "optional"]}}},
    {"id": "conflict_03", "desc": "safety 무관심 → 뒤에서 번복해 중요해짐",
     "utterance": "위험해도 상관없다고 생각했는데, 역시 안전한 길로 가는 게 낫겠어요.",
     "expect": {"safety": {"preference_label": "high", "explicitness_label": "explicit_soft"}}},
    {"id": "conflict_04", "desc": "comfort 선호 → 뒤에서 반대로 번복(경사 선호)",
     "utterance": "평지가 편할 줄 알았는데, 오히려 약간 경사진 게 재밌을 것 같아요.",
     "expect": {"comfort": {"preference_label": "low", "explicitness_label": "explicit_soft"}}},
    {"id": "conflict_05", "desc": "safety 무관심 → 뒤에서 번복해 중요해짐(상황 근거 포함)",
     "utterance": "안전 별로 신경 안 쓴다고 했었는데, 오늘은 밤이라 그런지 안전한 길로 가고 싶어졌어요.",
     "expect": {"safety": {"preference_label": "high", "explicitness_label": "explicit_soft"}}},
    {"id": "conflict_06", "desc": "comfort 요구 → 뒤에서 완화",
     "utterance": "편한 길로 부탁드렸었는데, 이번엔 오르막 있어도 괜찮아요.",
     "expect": {"comfort": {"preference_label": "low", "explicitness_label": ["explicit_soft", "optional"]}}},

    # =========================================================================
    # 5. 간접·추론 표현(inferred) — 키워드 없이 문맥으로만 (inferred_01~08)
    # =========================================================================
    {"id": "inferred_01", "desc": "safety, 인적 드묾을 통한 간접 표현",
     "utterance": "이 시간엔 사람이 아무도 없는 곳은 좀 그런데요.",
     "expect": {"safety": {"preference_label": "high", "explicitness_label": "inferred"}}},
    {"id": "inferred_02", "desc": "safety, 시설 부재를 통한 간접 표현",
     "utterance": "가로등도 없고 CCTV도 없는 데는 좀 꺼려져요.",
     "expect": {"safety": {"preference_label": "high", "explicitness_label": "inferred"}}},
    {"id": "inferred_03", "desc": "safety, 감정 표현(무섭다)을 통한 강한 간접 표현",
     "utterance": "차가 쌩쌩 달리는 큰 도로 옆은 진짜 못 걷겠어요, 무섭거든요.",
     "expect": {"safety": {"preference_label": "must", "explicitness_label": "inferred"}}},
    {"id": "inferred_04", "desc": "safety, 무관심을 통한 간접 표현",
     "utterance": "골목이 좀 으슥해도 저는 별로 신경 안 쓰이더라고요.",
     "expect": {"safety": {"preference_label": "low", "explicitness_label": "inferred"}}},
    {"id": "inferred_05", "desc": "comfort, 신체 반응을 통한 간접 표현",
     "utterance": "계단 많은 데는 숨이 차서 힘들어요.",
     "expect": {"comfort": {"preference_label": "high", "explicitness_label": "inferred"}}},
    {"id": "inferred_06", "desc": "comfort, 체력 부담을 통한 간접 표현",
     "utterance": "언덕 오르내리는 거 저한테는 좀 벅차요.",
     "expect": {"comfort": {"preference_label": "high", "explicitness_label": "inferred"}}},
    {"id": "inferred_07", "desc": "comfort, 무관심을 통한 간접 표현",
     "utterance": "울퉁불퉁한 흙길이어도 저는 재밌게 걸을 수 있어요.",
     "expect": {"comfort": {"preference_label": "low", "explicitness_label": "inferred"}}},
    {"id": "inferred_08", "desc": "comfort, 걱정 표현을 통한 간접 표현",
     "utterance": "계속 오르막이면 중간에 지칠 것 같아서 걱정이에요.",
     "expect": {"comfort": {"preference_label": "high", "explicitness_label": "inferred"}}},

    # =========================================================================
    # 6. 강조 표현 → explicit_hard (emphasis_01~05)
    # =========================================================================
    {"id": "emphasis_01", "desc": "ㅠㅠ 반복 + 꼭 → safety must/hard",
     "utterance": "안전한 길로요ㅠㅠㅠㅠ 꼭 부탁드려요ㅠㅠ",
     "expect": {"safety": {"preference_label": "must", "explicitness_label": "explicit_hard"}}},
    {"id": "emphasis_02", "desc": "단어 반복 + 절대 + !!! → comfort must/hard",
     "utterance": "평지평지평지!!! 오르막은 절대 싫어요!!!",
     "expect": {"comfort": {"preference_label": "must", "explicitness_label": "explicit_hard"}}},
    {"id": "emphasis_03", "desc": "단어 반복 + !!! → safety must/hard",
     "utterance": "안전 안전 안전!!! 이게 제일 중요해요!!!",
     "expect": {"safety": {"preference_label": "must", "explicitness_label": "explicit_hard"}}},
    {"id": "emphasis_04", "desc": "ㅋㅋㅋ 반복(강한 긍정이지만 필수는 아님) → comfort high/hard",
     "utterance": "편한 길ㅋㅋㅋㅋㅋ 진짜 완전 최고예요ㅋㅋㅋ",
     "expect": {"comfort": {"preference_label": "high", "explicitness_label": "explicit_hard"}}},
    {"id": "emphasis_05", "desc": "단어 3연속 반복 + !!!! → safety must/hard",
     "utterance": "위험한 데는 절대절대절대 안 돼요!!!!",
     "expect": {"safety": {"preference_label": "must", "explicitness_label": "explicit_hard"}}},

    # =========================================================================
    # 7. 무관 발화 → 완전히 빈 결과 (irrelevant_01~06)
    # =========================================================================
    {"id": "irrelevant_01", "desc": "거리·모드만 언급",
     "utterance": "여의도에서 3km 정도 순환하고 싶어요.",
     "expect": {"safety": None, "comfort": None}},
    {"id": "irrelevant_02", "desc": "추천 요청만, feature 언급 없음",
     "utterance": "다음 주에 갈 만한 코스 하나만 추천해주세요.",
     "expect": {"safety": None, "comfort": None}},
    {"id": "irrelevant_03", "desc": "날씨 잡담 + 산책 의사만",
     "utterance": "오늘 날씨가 좀 흐리네요, 그래도 산책은 하고 싶어요.",
     "expect": {"safety": None, "comfort": None}},
    {"id": "irrelevant_04", "desc": "시간만 언급",
     "utterance": "1시간 정도 걸을 수 있는 코스면 돼요.",
     "expect": {"safety": None, "comfort": None}},
    {"id": "irrelevant_05", "desc": "전반적 무관심(few-shot과 다른 문구)",
     "utterance": "여기서 가까운 데로 아무 데나 다녀올게요.",
     "expect": {"safety": None, "comfort": None}},
    {"id": "irrelevant_06", "desc": "거리 수정 요청만",
     "utterance": "출발지는 그대로 두고 거리만 5km로 바꿔주세요.",
     "expect": {"safety": None, "comfort": None}},

    # =========================================================================
    # 8. 경계선/모호 표현 — 인접 등급 사이, 정답 폭을 넓게 허용 (boundary_01~08)
    # =========================================================================
    {"id": "boundary_01", "desc": "high/must 경계",
     "utterance": "그래도 좀 안전했으면 좋겠어요.",
     "expect": {"safety": {"preference_label": ["high", "must"], "explicitness_label": ["explicit_soft", "optional"]}}},
    {"id": "boundary_02", "desc": "neutral/low 경계",
     "utterance": "편한 길이 낫긴 한데 그렇게 절실하진 않아요.",
     "expect": {"comfort": {"preference_label": ["neutral", "low"], "explicitness_label": ["explicit_soft", "optional"]}}},
    {"id": "boundary_03", "desc": "최소 조건형 표현, neutral/low 경계",
     "utterance": "위험하지만 않으면 저는 다 괜찮아요.",
     "expect": {"safety": {"preference_label": ["neutral", "low"], "explicitness_label": ["explicit_soft", "optional"]}}},
    {"id": "boundary_04", "desc": "'가급적' — optional 계열 마커",
     "utterance": "가급적 평평한 길로 부탁드려요.",
     "expect": {"comfort": {"preference_label": "high", "explicitness_label": ["optional", "explicit_soft"]}}},
    {"id": "boundary_05", "desc": "neutral/low 경계, 부드러운 부정",
     "utterance": "그렇게 안전을 따지는 편은 아니에요.",
     "expect": {"safety": {"preference_label": ["neutral", "low"], "explicitness_label": ["explicit_soft", "inferred"]}}},
    {"id": "boundary_06", "desc": "high/neutral 경계, 완곡한 긍정",
     "utterance": "안전한 길이면 더 좋을 것 같긴 해요.",
     "expect": {"safety": {"preference_label": ["high", "neutral"], "explicitness_label": ["explicit_soft", "optional"]}}},
    {"id": "boundary_07", "desc": "비교를 통한 완곡한 우선순위 하향",
     "utterance": "편안함보다는 그냥 짧은 게 중요해요.",
     "expect": {"comfort": {"preference_label": ["low", "neutral"], "explicitness_label": "explicit_soft"}}},
    {"id": "boundary_08", "desc": "high/must 경계, 조건부 필수 표현",
     "utterance": "안전 문제만 없으면 나머지는 아무래도 좋아요.",
     "expect": {"safety": {"preference_label": ["high", "must"], "explicitness_label": ["explicit_soft", "optional"]}}},

    # =========================================================================
    # 9. 트레이드오프 표현 — 한 축을 위해 다른 축을 희생 (tradeoff_01~05)
    # =========================================================================
    {"id": "tradeoff_01", "desc": "속도를 위해 안전을 희생",
     "utterance": "빠른 길이면 좀 위험해도 상관없어요.",
     "expect": {"safety": {"preference_label": "low", "explicitness_label": ["explicit_soft", "optional"]}}},
    {"id": "tradeoff_02", "desc": "거리를 희생해서라도 안전 확보",
     "utterance": "돌아가더라도 안전한 길로 가고 싶어요.",
     "expect": {"safety": {"preference_label": ["high", "must"], "explicitness_label": "explicit_soft"}}},
    {"id": "tradeoff_03", "desc": "최단거리를 위해 편안함을 희생",
     "utterance": "힘들어도 되니까 그냥 최단거리로 가주세요.",
     "expect": {"comfort": {"preference_label": "low", "explicitness_label": ["explicit_soft", "optional"]}}},
    {"id": "tradeoff_04", "desc": "시간을 희생해서라도 편안함 확보",
     "utterance": "시간이 걸려도 평지 위주로 부탁드려요.",
     "expect": {"comfort": {"preference_label": ["high", "must"], "explicitness_label": "explicit_soft"}}},
    {"id": "tradeoff_05", "desc": "심미성을 위해 안전을 희생(comfort는 언급 없음)",
     "utterance": "조금 위험하더라도 예쁜 길이면 상관없어요.",
     "expect": {"safety": {"preference_label": "low", "explicitness_label": ["explicit_soft", "optional"]},
                "comfort": None}},

    # =========================================================================
    # 10. 구어체·비정형 강건성 (informal_01~08)
    # =========================================================================
    {"id": "informal_01", "desc": "축약·반말",
     "utterance": "안전한데로좀ㅠ",
     "expect": {"safety": {"preference_label": ["high", "must"], "explicitness_label": ["explicit_soft", "explicit_hard"]}}},
    {"id": "informal_02", "desc": "반복 거부어(노노)로 강한 선호 표현",
     "utterance": "위험한거 노노 안전한길로",
     "expect": {"safety": {"preference_label": ["high", "must"], "explicitness_label": ["explicit_soft", "explicit_hard"]}}},
    {"id": "informal_03", "desc": "비속어 섞인 강조체",
     "utterance": "안전?? 그거 존나중요함",
     "expect": {"safety": {"preference_label": ["high", "must"], "explicitness_label": "explicit_hard"}}},
    {"id": "informal_04", "desc": "사투리/축약 어미",
     "utterance": "평지루다가 가주셈",
     "expect": {"comfort": {"preference_label": "high", "explicitness_label": "explicit_soft"}}},
    {"id": "informal_05", "desc": "단어 하나만 입력",
     "utterance": "안전",
     "expect": {"safety": {"preference_label": ["high", "neutral"], "explicitness_label": ["explicit_soft", "inferred"]}}},
    {"id": "informal_06", "desc": "구어체 번복 후 전반적 무관심 → 결과에서 제외",
     "utterance": "그니까 안전한데로... 아 몰라 걍 아무데나.",
     "expect": {"safety": None, "comfort": None}},
    {"id": "informal_07", "desc": "비속어 섞인 긍정 강조",
     "utterance": "야 안전한거 개꿀 좋아함ㅋㅋㅋㅋ",
     "expect": {"safety": {"preference_label": ["high", "must"], "explicitness_label": "explicit_hard"}}},
    {"id": "informal_08", "desc": "오타(펴안한) + 축약 어미",
     "utterance": "펴안한 길로 가고싶어영",
     "expect": {"comfort": {"preference_label": "high", "explicitness_label": "explicit_soft"}}},

    # =========================================================================
    # 11. 재현성(패러프레이즈 일관성) — grid의 특정 조합을 다른 문구로 재현 (paraphrase_01~05)
    # =========================================================================
    {"id": "paraphrase_01", "desc": "grid_01(safety must/hard)의 패러프레이즈",
     "utterance": "위험한 골목은 진짜 안 돼요, 반드시반드시 안전한 길로 가야 해요!!",
     "expect": {"safety": {"preference_label": "must", "explicitness_label": "explicit_hard"}}},
    {"id": "paraphrase_02", "desc": "grid_20(comfort high/soft)의 패러프레이즈",
     "utterance": "걷기 편안한 코스로 가고 싶어요.",
     "expect": {"comfort": {"preference_label": "high", "explicitness_label": "explicit_soft"}}},
    {"id": "paraphrase_03", "desc": "grid_12(safety low/soft)의 패러프레이즈",
     "utterance": "안전은 크게 신경 쓰지 않는 편이에요.",
     "expect": {"safety": {"preference_label": "low", "explicitness_label": "explicit_soft"}}},
    {"id": "paraphrase_04", "desc": "grid_16(comfort must/soft)의 패러프레이즈",
     "utterance": "경사진 곳이면 저는 도저히 못 걸어요, 평지로 부탁드려요.",
     "expect": {"comfort": {"preference_label": "must", "explicitness_label": "explicit_soft"}}},
    {"id": "paraphrase_05", "desc": "inferred_05(comfort high/inferred)의 패러프레이즈",
     "utterance": "오르내리는 계단이 많으면 저는 좀 지칠 것 같아요.",
     "expect": {"comfort": {"preference_label": "high", "explicitness_label": "inferred"}}},

    # =========================================================================
    # 12. 기존 선호 번복 표현 — "아까는 ~했는데" 식으로 과거를 언급하며 뒤집는 표현
    #     (revision_01~07). weight_extractor는 이전 턴의 라벨을 프롬프트로 못 받으므로
    #     이 카테고리는 "번복 정보가 이번 발화 안에 다 담긴 경우"만 다룬다 — 위 모듈
    #     docstring과 desc의 "취소" 판단 기준 참고.
    # =========================================================================
    {"id": "revision_01", "desc": "과거 강조 언급 → 이번 발화에서 명시적으로 낮춤",
     "utterance": "아까 안전한 길로 해달라고 했는데, 사실 그렇게까지 안 중요해요.",
     "expect": {"safety": {"preference_label": "low", "explicitness_label": "explicit_soft"}}},
    {"id": "revision_02", "desc": "과거 선호 언급 → 이번엔 반대로",
     "utterance": "원래는 편한 길이 좋다고 했는데 오늘은 좀 험해도 재밌을 것 같아요.",
     "expect": {"comfort": {"preference_label": "low", "explicitness_label": "explicit_soft"}}},
    {"id": "revision_03", "desc": "'없던 걸로' 취소 → 언급 자체가 없었던 것처럼 결과에서 제외",
     "utterance": "다시 생각해보니 안전 얘기는 없던 걸로 해주세요.",
     "expect": {"safety": None}},
    {"id": "revision_04", "desc": "'취소' + 명시적 무관심 진술 → low(취소 자체보다 뒤따르는 무관심 진술이 근거)",
     "utterance": "그냥 취소, 위험해도 상관없어요.",
     "expect": {"safety": {"preference_label": "low", "explicitness_label": ["explicit_soft", "optional"]}}},
    {"id": "revision_05", "desc": "과거 발언 무시 지시 + 새 선호 진술",
     "utterance": "역시 편한 길이 나을 것 같아요, 아까 한 말은 무시해주세요.",
     "expect": {"comfort": {"preference_label": "high", "explicitness_label": "explicit_soft"}}},
    {"id": "revision_06", "desc": "'취소하고' + 무관한 요청으로 전환 → 제외",
     "utterance": "안전 얘기했던 거 취소하고, 그냥 빠른 길로만 가주세요.",
     "expect": {"safety": None, "comfort": None}},
    {"id": "revision_07", "desc": "비교형 번복 — comfort를 명시적으로 낮추고 safety를 새로 강조",
     "utterance": "다시 말할게요, 편안한 거 말고 이번엔 안전한 게 더 중요해요.",
     "expect": {"comfort": {"preference_label": "low", "explicitness_label": "explicit_soft"},
                "safety": {"preference_label": ["high", "must"], "explicitness_label": "explicit_soft"}}},
]

assert len(CASES) == 100, f"케이스 수가 100이 아닙니다: {len(CASES)}"
assert len({c['id'] for c in CASES}) == len(CASES), "중복된 case id가 있습니다."


# ── 비교 유틸 ────────────────────────────────────────────────────────────────
def _label_match(expected, actual: str) -> bool:
    if isinstance(expected, (list, tuple, set)):
        return actual in expected
    return actual == expected


def evaluate(case: dict, result: dict) -> list[str]:
    """케이스 기대값과 실제 추출 결과를 대조해 실패 사유 리스트를 반환(빈 리스트면 통과)."""
    fails: list[str] = []
    for axis, expected in case["expect"].items():
        actual = result.get(axis)
        if expected is None:
            if actual is not None:
                fails.append(f"{axis}: 결과에 없어야 하는데 {actual} 나옴")
            continue
        if actual is None:
            fails.append(f"{axis}: {expected} 기대했는데 결과에서 빠짐")
            continue
        if not _label_match(expected["preference_label"], actual["preference_label"]):
            fails.append(
                f"{axis}.preference_label: 기대 {expected['preference_label']} / 실제 {actual['preference_label']}"
            )
        if not _label_match(expected["explicitness_label"], actual["explicitness_label"]):
            fails.append(
                f"{axis}.explicitness_label: 기대 {expected['explicitness_label']} / 실제 {actual['explicitness_label']}"
            )
    return fails


# ── 실행 ────────────────────────────────────────────────────────────────────
async def _one_call(client: GPTClient, parser: PydanticOutputParser, utterance: str) -> dict:
    """WeightExtractor.run()과 동일한 프롬프트·입력변수·파서로 직접 호출한다(Node를
    거치지 않는다 — State/mode 분기는 이 스크립트의 검증 범위 밖이다)."""
    result: FeatureLabelMap = await client.get_response(
        prompt_name="weight_extraction",
        input_variables={
            "user_input": utterance,
            "feature_tags": [tag.value for tag in FeatureTag],
            "format_instructions": parser.get_format_instructions(),
        },
        parser=parser,
    )
    return {
        tag.value: {"preference_label": label.preference_label, "explicitness_label": label.explicitness_label}
        for tag, label in result.root.items()
    }


async def run(args: argparse.Namespace) -> int:
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY가 없습니다(.env 확인).")
        return 2

    cases = CASES
    if args.only:
        wanted = {c.strip() for c in args.only.split(",")}
        cases = [c for c in CASES if c["id"] in wanted or _category_of(c["id"]) in wanted]
        matched = {c["id"] for c in cases} | {_category_of(c["id"]) for c in cases}
        missing = wanted - matched
        if missing:
            print(f"알 수 없는 케이스 id/카테고리: {sorted(missing)}")
            return 2

    client = GPTClient()
    if args.model or args.temperature is not None:
        client.llm = ChatOpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            model=args.model or "gpt-4o-mini",
            temperature=args.temperature if args.temperature is not None else 0.1,
        )
    parser = PydanticOutputParser(pydantic_object=FeatureLabelMap)

    print(f"weight_extraction.yaml eval | model={client.llm.model_name} "
          f"temperature={client.llm.temperature} repeat={args.repeat} cases={len(cases)}")
    print("=" * 78)

    passed = failed = 0
    cat_stats: dict[str, list[int]] = {}
    for case in cases:
        cat = _category_of(case["id"])
        cat_stats.setdefault(cat, [0, 0])

        runs: list[tuple[dict, list[str]]] = []
        for _ in range(args.repeat):
            try:
                result = await _one_call(client, parser, case["utterance"])
            except Exception as exc:  # 파서·LLM 실패도 실패 사유로 기록하고 계속 진행한다
                runs.append(({}, [f"호출/파싱 실패: {exc!r}"]))
                continue
            runs.append((result, evaluate(case, result)))

        ok_runs = sum(1 for _, f in runs if not f)
        is_pass = ok_runs == args.repeat
        passed += is_pass
        failed += not is_pass
        cat_stats[cat][0 if is_pass else 1] += 1

        tag = "PASS" if is_pass else ("FLAKY" if 0 < ok_runs < args.repeat else "FAIL")
        consist = f" ({ok_runs}/{args.repeat})" if args.repeat > 1 else ""
        print(f"[{tag}{consist}] {case['id']} — {case['desc']}")
        print(f"       발화: {case['utterance']}")
        print(f"       기대: {case['expect']}")

        if not is_pass or args.verbose:
            seen: set[str] = set()
            for result, fails in runs:
                sig = json.dumps(result, ensure_ascii=False, sort_keys=True)
                if sig in seen and not args.verbose:
                    continue
                seen.add(sig)
                print(f"       → 결과: {result}")
                for f in fails:
                    print(f"         ✗ {f}")
        print()

    print("=" * 78)
    print(f"결과: {passed} PASS / {failed} FAIL  (총 {len(cases)})")
    print("-- 카테고리별 --")
    for cat, (p, f) in sorted(cat_stats.items(), key=lambda kv: CATEGORY_TITLES.get(kv[0], kv[0])):
        title = CATEGORY_TITLES.get(cat, cat)
        print(f"  {title:<30} {p} PASS / {f} FAIL")
    return 1 if failed else 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="weight_extraction.yaml 프롬프트 검증")
    p.add_argument("--repeat", type=int, default=1, help="케이스별 반복 호출 수(비결정성 확인)")
    p.add_argument("--only", type=str, default="", help="쉼표로 구분한 케이스 id 또는 카테고리명만 실행")
    p.add_argument("--model", type=str, default="", help="모델 override (기본: gpt-4o-mini)")
    p.add_argument("--temperature", type=float, default=None, help="temperature override")
    p.add_argument("--verbose", action="store_true", help="통과 케이스도 결과 상세 출력")
    return p.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parse_args())))
