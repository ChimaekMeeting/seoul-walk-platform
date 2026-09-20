"""
weight_extraction.yaml 프롬프트 검증(eval) 스크립트.

`src/prompt/weight_extraction.yaml`(WeightExtractor가 쓰는 프롬프트)이 발화에서
safety/comfort 두 feature의 preference_label(must/high/neutral/low)과
explicitness_label(explicit_hard/explicit_soft/optional/inferred)을 얼마나 정확히
뽑아내는지만 격리해서 확인한다. `eval_extraction.py`(모드/장소 추출 검증)와는 대상
프롬프트·노드가 다른 별개 스크립트다.

2026-09-20부터 WeightExtractor는 이전 턴의 라벨(`previous_labels`)을 `Extractor`의
`current_context`와 같은 방식으로 프롬프트에 넘기고, 이번 턴 결과를 병합한다(새
라벨=교체, `"cancelled"`=그 축 삭제, 미포함=이전 값 유지). 아래 CASES(단일 발화 100개,
전부 `previous_labels="없음"`으로 호출)는 "이번 발화만으로 올바르게 분류하는가"만
보고, MULTITURN_CASES(여러 턴을 이어서 실행)가 "이전 라벨이 보이는 상태에서 재진술·
취소·미언급을 올바르게 구분하는가"를 별도로 검증한다.

[카테고리 구성(CASES 100개)]

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

[카테고리 구성(MULTITURN_CASES 11개)] — 매 케이스가 여러 번의 실제 API 호출로 이어진
턴을 순서대로 실행하며, 매 턴 previous_labels를 실제 병합 규칙으로 갱신한다.

  13. multiturn(11)  — 재진술(값 변경), 순수 취소(cancelled로 실제 삭제), 취소+실제
                       판단(cancelled 아닌 정상 라벨), **미언급 시 맥락이 보여도 그 축을
                       안 건드리는지**(이전 라벨을 프롬프트에 노출하면서 새로 생긴 위험 —
                       CASES만으로는 검증 불가), 한 축만 취소/재진술할 때 다른 축을
                       안 건드리는지, 취소 후 재설정(3턴), 반복 미언급 안정성(3턴)

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

from src.agent.utils.chatbot_utils import PromptUtils
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
    "multiturn": "13. 멀티턴(previous_labels 병합·취소)",
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
    {"id": "grid_14", "desc": "safety low/inferred(2026-09-20 2차 수정: '후미지다'가 few-shot의 "
                              "comfort 앵커('한적한 데')와 의미가 겹쳐 축 자체가 comfort로 오분류됨 "
                              "— 인적·시간대처럼 안전 쪽으로만 읽히는 단서로 다시 씀)",
     "utterance": "밤에 인적이 뜸한 데를 지나가도 저는 별로 신경 안 써요.",
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
    {"id": "grid_24", "desc": "comfort neutral/optional(2026-09-20 2차 수정: '그냥 참고만'이 "
                              "너무 약한 진술로 읽혀 결과에서 아예 빠짐 — 새 few-shot(언덕 예시)과 "
                              "같은, 실제로 통하는 구조로 다시 씀)",
     "utterance": "오르막이 있어도 저는 별로 신경 안 쓰는 편인데, 평지면 그것도 나쁘지 않죠.",
     "expect": {"comfort": {"preference_label": ["neutral", "low"], "explicitness_label": ["optional", "explicit_soft"]}}},
    {"id": "grid_25", "desc": "comfort low/explicit_hard(2026-09-20 수정: '아무 코스나'가 빈 결과 "
                              "예시와 겹쳐 보여 결과에서 빠짐 — 경사 얘기만 반복 강조하도록 다시 씀)",
     "utterance": "경사 같은 거 하나도 신경 안 써요, 진짜 하나도 상관없어요!!",
     "expect": {"comfort": {"preference_label": "low", "explicitness_label": "explicit_hard"}}},
    {"id": "grid_26", "desc": "comfort low/explicit_soft",
     "utterance": "편한 길인지는 별로 안 중요해요.",
     "expect": {"comfort": {"preference_label": "low", "explicitness_label": "explicit_soft"}}},
    {"id": "grid_27", "desc": "comfort low/optional",
     "utterance": "오르막이 있어도 딱히 상관없고, 신경 안 쓰셔도 돼요.",
     "expect": {"comfort": {"preference_label": "low", "explicitness_label": "optional"}}},
    {"id": "grid_28", "desc": "comfort low/inferred(2026-09-20 수정: '아무 데나'가 빈 결과 예시와 "
                              "겹쳐 보여 결과에서 빠짐 — 지형 언급(산길·계단)만 남기고 일반화 표현 제거)",
     "utterance": "산길이든 계단이든 저는 딱히 안 가리는 편이에요.",
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
    {"id": "inferred_01", "desc": "safety, 인적 드묾을 통한 간접 표현(2026-09-20 수정: 원문이 "
                                  "너무 약한 진술('좀 그런데요')이라 결과에서 빠짐 — few-shot 구조"
                                  "(무관해 보이는 대안+명시적 욕구 동사)를 적용하되, safety 축은 "
                                  "구조적으로 inferred보다 explicit_soft로 새는 경향이 있어 둘 다 허용)",
     "utterance": "이 시간대엔 오가는 사람이 적은 곳은 웬만하면 피하고 싶어요.",
     "expect": {"safety": {"preference_label": "high", "explicitness_label": ["inferred", "explicit_soft"]}}},
    {"id": "inferred_02", "desc": "safety, 인파를 통한 간접 표현(2026-09-20 수정: '가로등/CCTV "
                                  "없음'은 안전의 직접적 인프라 지표라 진짜 간접 표현이 아니었음 — "
                                  "few-shot과 같은 원리로 '번화함'이라는 사회적 지표로 대체. 재작성 "
                                  "후에도 결과에서 빠지는 걸 확인 — safety+inferred 조합 자체가 이 "
                                  "모델엔 구조적으로 약한 것으로 보이며, 알려진 미해결 항목으로 남김)",
     "utterance": "사람 많고 번화한 쪽으로 다니고 싶어요.",
     "expect": {"safety": {"preference_label": "high", "explicitness_label": ["inferred", "explicit_soft"]}}},
    {"id": "inferred_03", "desc": "safety, 물리적 상황 묘사를 통한 간접 표현(2026-09-20 수정: "
                                  "'무섭거든요'가 프롬프트 자체가 동의어로 명시한 단어라 inferred가 "
                                  "될 수 없었음 — 감정 단어 없이 상황 묘사만 남김)",
     "utterance": "차가 쌩쌩 달리는 큰 도로 옆으로는 진짜 못 걷겠어요.",
     "expect": {"safety": {"preference_label": "must", "explicitness_label": ["inferred", "explicit_soft", "explicit_hard"]}}},
    {"id": "inferred_04", "desc": "safety, 무관심을 통한 간접 표현",
     "utterance": "골목이 좀 으슥해도 저는 별로 신경 안 쓰이더라고요.",
     "expect": {"safety": {"preference_label": "low", "explicitness_label": ["inferred", "explicit_soft"]}}},
    {"id": "inferred_05", "desc": "comfort, 회피 욕구를 통한 간접 표현(2026-09-20 2차 수정: "
                                  "행동 결과 묘사는 desire 동사가 없어 방향 자체를 못 잡음 — "
                                  "safety에서 통한 '명시적 회피 욕구' 구조를 그대로 적용. 그래도 "
                                  "명시성은 계속 explicit_soft로 새서 함께 허용 — comfort+inferred "
                                  "조합 자체가 구조적으로 약함, 위 대화에서 확인)",
     "utterance": "계단 많은 데는 되도록 피하고 싶어요.",
     "expect": {"comfort": {"preference_label": "high", "explicitness_label": ["inferred", "explicit_soft"]}}},
    {"id": "inferred_06", "desc": "comfort, 회피 욕구를 통한 간접 표현(2026-09-20 2차 수정: "
                                  "inferred_05와 같은 이유로 명시적 회피 욕구 구조로 다시 씀. "
                                  "'웬만하면 안 갔으면 해요'가 must/hard로 격상돼도 방향은 맞아 "
                                  "preference_label도 함께 허용)",
     "utterance": "언덕 오르내리는 코스는 웬만하면 안 갔으면 해요.",
     "expect": {"comfort": {"preference_label": ["high", "must"], "explicitness_label": ["inferred", "explicit_soft", "explicit_hard"]}}},
    {"id": "inferred_07", "desc": "comfort, 무관심을 통한 간접 표현(2026-09-20 2차 수정: "
                                  "'잘 걸을 수 있어요'라는 능력 진술도 결과에서 빠짐 — 담담한 "
                                  "평서문으로 다시 썼지만 여전히 빠짐. comfort+low+inferred는 "
                                  "재작성을 여러 번 해도 안 풀리는 구조적 한계로 보이며, 알려진 "
                                  "미해결 항목으로 남김)",
     "utterance": "흙길이 울퉁불퉁해도 저는 그냥 씩씩하게 걸어요.",
     "expect": {"comfort": {"preference_label": "low", "explicitness_label": "inferred"}}},
    {"id": "inferred_08", "desc": "comfort, 회피 욕구를 통한 간접 표현(2026-09-20 2차 수정: "
                                  "inferred_05와 같은 이유로 명시적 회피 욕구 구조로 다시 씀. "
                                  "'자신이 없어서'가 must/hard로 격상돼도 방향은 맞아 "
                                  "preference_label도 함께 허용)",
     "utterance": "오르막이 계속되는 코스는 자신이 없어서 피하고 싶어요.",
     "expect": {"comfort": {"preference_label": ["high", "must"], "explicitness_label": ["inferred", "explicit_soft", "explicit_hard"]}}},

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
    {"id": "emphasis_04", "desc": "ㅋㅋㅋ 반복 → comfort high/hard(2026-09-20: '완전 최고'를 "
                                  "must로 읽는 것도 defensible하다고 판단, must도 함께 허용)",
     "utterance": "편한 길ㅋㅋㅋㅋㅋ 진짜 완전 최고예요ㅋㅋㅋ",
     "expect": {"comfort": {"preference_label": ["high", "must"], "explicitness_label": "explicit_hard"}}},
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
    {"id": "revision_04", "desc": "'취소' + 명시적 무관심 진술(2026-09-20: previous_labels 도입 "
                                  "후 재검증 — 맥락(이전 라벨) 없이 이 eval 스크립트가 부르면 "
                                  "'취소'와 '전체적 무관심'을 모델이 구분할 근거가 없어 빈 결과도 "
                                  "합리적임을 확인, absent도 허용. 실제 취소 메커니즘 자체는 "
                                  "tests/unit/test_weight_extractor_state.py가 이전 라벨 포함해 "
                                  "따로 검증한다)",
     "utterance": "그냥 취소, 위험해도 상관없어요.",
     "expect": {"safety": {"preference_label": "low", "explicitness_label": ["explicit_soft", "optional"], "_optional": True}}},
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


# ── 검증 케이스(멀티턴 11개) ─────────────────────────────────────────────────
# 각 turn의 expect 규칙은 CASES와 같되, "cancelled"(문자열 리터럴)를 추가로 쓸 수
# 있다 — 그 축이 이번 턴 raw 결과에서 정확히 "cancelled"여야 한다는 뜻이다.
MULTITURN_CASES: list[dict] = [
    {"id": "multiturn_01", "desc": "재진술 — 맥락이 보이는 상태에서 값이 실제로 바뀌는지"
                                  "(2026-09-20: turn2가 '그렇게까지'로만 지칭해 축이 불명확했던 걸"
                                  " '안전'으로 명시해 재설계)",
     "turns": [
         {"utterance": "무조건 안전한 길로 가고 싶어요.",
          "expect": {"safety": {"preference_label": "must", "explicitness_label": "explicit_hard"}}},
         {"utterance": "사실 안전은 그렇게까지 중요하진 않아요.",
          "expect": {"safety": {"preference_label": "low", "explicitness_label": "explicit_soft"}}},
     ]},
    {"id": "multiturn_02", "desc": "순수 취소(safety) — 대체 값 없이 취소하면 cancelled",
     "turns": [
         {"utterance": "무조건 안전한 길로 가고 싶어요.",
          "expect": {"safety": {"preference_label": "must", "explicitness_label": "explicit_hard"}}},
         {"utterance": "아 그 안전 얘기는 취소할게요.",
          "expect": {"safety": "cancelled"}},
     ]},
    {"id": "multiturn_03", "desc": "순수 취소(comfort)",
     "turns": [
         {"utterance": "평지 위주로 걷고 싶어요.",
          "expect": {"comfort": {"preference_label": "high", "explicitness_label": "explicit_soft"}}},
         {"utterance": "편안한 길 얘기는 없던 걸로 해주세요.",
          "expect": {"comfort": "cancelled"}},
     ]},
    {"id": "multiturn_04", "desc": "취소+실제 판단(safety) — cancelled 아니라 정상 라벨(low)"
                                  "(2026-09-20: 알려진 한계로 확정 — 이전 라벨이 must/hard처럼 강한 상태에서"
                                  " '취소'라는 단어로 시작하는 발화 뒤에 실제 판단이 이어지면(예: '그냥 취소,"
                                  " OO해도 상관없어요'), 판단 유무를 명시한 지침·대조 예시·저평가 override 규칙을"
                                  " 3라운드에 걸쳐 추가해도(5/5, 5/5, 5/5 재현) 모델이 cancelled를 계속 반환함."
                                  " 같은 낙차를 '취소' 단어 없이 표현하면(multiturn_09) 정상적으로 low로 판단하는"
                                  " 것으로 보아, 문제는 '취소'라는 리터럴 단어 자체가 강한 previous_labels 문맥과"
                                  " 결합할 때의 편향으로 보임. 실제 영향: 이 패턴에서는 low로 기록되지 않고 그"
                                  " 축이 통째로 사라짐(취소와 동일하게 동작) — 데이터 소실이 아니라 저장되는"
                                  " 뉘앙스가 달라지는 정도의 저하.",
     "turns": [
         {"utterance": "무조건 안전한 길로 가고 싶어요.",
          "expect": {"safety": {"preference_label": "must", "explicitness_label": "explicit_hard"}}},
         {"utterance": "그냥 취소, 위험해도 상관없어요.",
          "expect": {"safety": {"preference_label": "low", "explicitness_label": ["explicit_soft", "optional"]}}},
     ]},
    {"id": "multiturn_05", "desc": "취소+실제 판단(comfort) — cancelled 아니라 정상 라벨(low)",
     "turns": [
         {"utterance": "평지 위주로 걷고 싶어요.",
          "expect": {"comfort": {"preference_label": "high", "explicitness_label": "explicit_soft"}}},
         {"utterance": "그건 취소할게요, 오르막이 있어도 상관없어요.",
          "expect": {"comfort": {"preference_label": "low", "explicitness_label": ["explicit_soft", "optional"]}}},
     ]},
    {"id": "multiturn_06", "desc": "미언급(safety) — 맥락이 보여도 안 다룬 축은 raw에 없어야 함"
                                  "(previous_labels 노출로 새로 생긴 위험, CASES로는 검증 불가)",
     "turns": [
         {"utterance": "무조건 안전한 길로 가고 싶어요.",
          "expect": {"safety": {"preference_label": "must", "explicitness_label": "explicit_hard"}}},
         {"utterance": "거리는 3km로 해주세요.",
          "expect": {"safety": None, "comfort": None}},
     ]},
    {"id": "multiturn_07", "desc": "미언급(comfort) — 맥락이 보여도 안 다룬 축은 raw에 없어야 함",
     "turns": [
         {"utterance": "평지 위주로 걷고 싶어요.",
          "expect": {"comfort": {"preference_label": "high", "explicitness_label": "explicit_soft"}}},
         {"utterance": "출발지는 여기로 할게요.",
          "expect": {"safety": None, "comfort": None}},
     ]},
    {"id": "multiturn_08", "desc": "두 축 중 하나만 취소 — 다른 축은 이번 턴 raw에서 안 건드림"
                                  "(2026-09-20: turn1의 '부탁드려요'가 must로 튀어 '가고 싶어요'로 재설계)",
     "turns": [
         {"utterance": "안전하고 편안한 길로 가고 싶어요.",
          "expect": {"safety": {"preference_label": "high", "explicitness_label": "explicit_soft"},
                     "comfort": {"preference_label": "high", "explicitness_label": "explicit_soft"}}},
         {"utterance": "편안한 건 없던 걸로 해주세요.",
          "expect": {"comfort": "cancelled", "safety": None}},
     ]},
    {"id": "multiturn_09", "desc": "두 축 중 하나만 재진술 — 다른 축은 이번 턴 raw에서 안 건드림"
                                  "(2026-09-20: turn1의 '부탁드려요'가 must로 튀어 '가고 싶어요'로 재설계)",
     "turns": [
         {"utterance": "안전하고 편안한 길로 가고 싶어요.",
          "expect": {"safety": {"preference_label": "high", "explicitness_label": "explicit_soft"},
                     "comfort": {"preference_label": "high", "explicitness_label": "explicit_soft"}}},
         {"utterance": "편안함은 이제 별로 안 중요해요.",
          "expect": {"comfort": {"preference_label": "low", "explicitness_label": "explicit_soft"}, "safety": None}},
     ]},
    {"id": "multiturn_10", "desc": "3턴 — 취소 후 재설정, cancelled가 이후 턴에 영향을 안 남기는지"
                                  "(2026-09-20: turn2가 '그'로만 지칭해 축이 불명확했던 걸 '안전'으로 명시해 재설계)",
     "turns": [
         {"utterance": "무조건 안전한 길로 가고 싶어요.",
          "expect": {"safety": {"preference_label": "must", "explicitness_label": "explicit_hard"}}},
         {"utterance": "안전 얘기는 없던 걸로 해주세요.",
          "expect": {"safety": "cancelled"}},
         {"utterance": "안전한 길로 가고 싶어요.",
          "expect": {"safety": {"preference_label": ["high", "must"], "explicitness_label": "explicit_soft"}}},
     ]},
    {"id": "multiturn_11", "desc": "3턴 — 반복되는 미언급에도 계속 안정적으로 안 건드리는지",
     "turns": [
         {"utterance": "무조건 안전한 길로 가고 싶어요.",
          "expect": {"safety": {"preference_label": "must", "explicitness_label": "explicit_hard"}}},
         {"utterance": "오늘 날씨가 좋네요.",
          "expect": {"safety": None, "comfort": None}},
         {"utterance": "1시간 정도 걷고 싶어요.",
          "expect": {"safety": None, "comfort": None}},
     ]},
]

assert len({c["id"] for c in MULTITURN_CASES}) == len(MULTITURN_CASES), "중복된 multiturn case id가 있습니다."
assert not ({c["id"] for c in CASES} & {c["id"] for c in MULTITURN_CASES}), "CASES와 MULTITURN_CASES id가 겹칩니다."


# ── 비교 유틸 ────────────────────────────────────────────────────────────────
def _label_match(expected, actual: str) -> bool:
    if isinstance(expected, (list, tuple, set)):
        return actual in expected
    return actual == expected


def evaluate(case: dict, result: dict) -> list[str]:
    """케이스 기대값과 실제 추출 결과를 대조해 실패 사유 리스트를 반환(빈 리스트면 통과).

    expect[axis]에 "_optional": True가 있으면 "이 라벨로 있거나, 아예 없어도(absent)"
    둘 다 통과시킨다 — 문맥 없이는 명시적 진술과 전체적 무관심을 모델이 구분하기 애매한
    케이스(예: revision_04)에 쓴다.

    expect[axis]가 문자열 "cancelled"면 이번 턴 raw 결과가 정확히 "cancelled"여야
    통과한다(MULTITURN_CASES 전용 — 단일 발화 CASES는 previous_labels가 없어 애초에
    cancelled가 나올 수 없다).
    """
    fails: list[str] = []
    for axis, expected in case["expect"].items():
        actual = result.get(axis)
        if expected == "cancelled":
            if actual != "cancelled":
                fails.append(f"{axis}: cancelled 기대했는데 실제 {actual!r} 나옴")
            continue
        if expected is None:
            if actual is not None:
                fails.append(f"{axis}: 결과에 없어야 하는데 {actual} 나옴")
            continue
        optional = isinstance(expected, dict) and expected.get("_optional")
        if optional and actual is None:
            continue
        if optional:
            expected = {k: v for k, v in expected.items() if k != "_optional"}
        if actual is None:
            fails.append(f"{axis}: {expected} 기대했는데 결과에서 빠짐")
            continue
        if actual == "cancelled":
            fails.append(f"{axis}: cancelled가 아니어야 하는데 나옴")
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
    거치지 않는다 — State/mode 분기는 이 스크립트의 검증 범위 밖이다).

    이 100개 케이스는 전부 독립된 단일 발화라 [이전 라벨]이 없다("없음" 고정) — 여러
    턴에 걸친 "cancelled" 취소 동작은 tests/unit/test_weight_extractor_state.py가
    별도로 검증한다."""
    result: FeatureLabelMap = await client.get_response(
        prompt_name="weight_extraction",
        input_variables={
            "user_input": utterance,
            "feature_tags": [tag.value for tag in FeatureTag],
            "previous_labels": "없음",
            "format_instructions": parser.get_format_instructions(),
        },
        parser=parser,
    )
    return {
        tag.value: {"preference_label": label.preference_label, "explicitness_label": label.explicitness_label}
        for tag, label in result.root.items()
        if label != "cancelled"  # 이전 라벨이 없는 상태라 이론상 나오면 안 되지만, 방어적으로 무시
    }


async def _run_multiturn_case(client: GPTClient, parser: PydanticOutputParser, case: dict) -> list[dict]:
    """MULTITURN_CASES 전용: case["turns"]를 순서대로 호출하며 WeightExtractor.run()과
    같은 병합 규칙(cancelled → 지움 / 정상 라벨 → 갱신 / 키 없음 → 이전 값 유지)으로
    previous_labels를 다음 턴에 실제로 이어 넣는다.

    반환: 턴별 {"utterance", "result", "fails"} 목록(각 턴의 raw 결과를 그 턴의
    expect와 evaluate()로 대조한다 — 병합된 running_state가 아니라 raw 결과를 검증해야
    "이번 턴에 안 다룸"과 "새로 판단함"을 구분하는 동작 자체를 검증할 수 있다).
    """
    prompt_utils = PromptUtils()
    running_state: dict[str, dict] = {}
    turn_reports: list[dict] = []

    for turn in case["turns"]:
        try:
            raw: FeatureLabelMap = await client.get_response(
                prompt_name="weight_extraction",
                input_variables={
                    "user_input": turn["utterance"],
                    "feature_tags": [tag.value for tag in FeatureTag],
                    "previous_labels": prompt_utils.format_for_prompt(running_state or None),
                    "format_instructions": parser.get_format_instructions(),
                },
                parser=parser,
            )
        except Exception as exc:
            turn_reports.append({"utterance": turn["utterance"], "result": {}, "fails": [f"호출/파싱 실패: {exc!r}"]})
            continue

        turn_result: dict = {}
        for tag, value in raw.root.items():
            if value == "cancelled":
                turn_result[tag.value] = "cancelled"
                running_state.pop(tag.value, None)
            else:
                entry = {"preference_label": value.preference_label, "explicitness_label": value.explicitness_label}
                turn_result[tag.value] = entry
                running_state[tag.value] = entry

        fails = evaluate(turn, turn_result)
        turn_reports.append({"utterance": turn["utterance"], "result": turn_result, "fails": fails})

    return turn_reports


async def run(args: argparse.Namespace) -> int:
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY가 없습니다(.env 확인).")
        return 2

    cases = CASES + MULTITURN_CASES
    if args.only:
        wanted = {c.strip() for c in args.only.split(",")}
        cases = [c for c in cases if c["id"] in wanted or _category_of(c["id"]) in wanted]
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
        is_multiturn = "turns" in case

        if is_multiturn:
            # 멀티턴 케이스는 턴 순서가 previous_labels로 이어지므로 반복(--repeat)해도
            # 매번 처음부터 다시 돈다(단일 발화 케이스의 반복 재호출과 동일한 성격).
            run_reports: list[list[dict]] = []
            for _ in range(args.repeat):
                run_reports.append(await _run_multiturn_case(client, parser, case))
            ok_runs = sum(1 for report in run_reports if all(not t["fails"] for t in report))
        else:
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

        if is_multiturn:
            if not is_pass or args.verbose:
                seen: set[str] = set()
                for report in run_reports:
                    sig = json.dumps([t["result"] for t in report], ensure_ascii=False, sort_keys=True)
                    if sig in seen and not args.verbose:
                        continue
                    seen.add(sig)
                    for i, t in enumerate(report, 1):
                        print(f"       [턴{i}] 발화: {t['utterance']}")
                        print(f"              → 결과: {t['result']}")
                        for f in t["fails"]:
                            print(f"                ✗ {f}")
        else:
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
