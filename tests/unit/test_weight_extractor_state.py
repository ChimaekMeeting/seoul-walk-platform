"""
tests/unit/test_weight_extractor_state.py

WeightExtractor.run()이 여러 턴에 걸쳐 state.feature_labels를 어떻게 다루는지 검증한다.

scripts/eval_weight_extraction.py는 "발화 하나를 주면 LLM이 라벨을 정확히 뽑는가"
(프롬프트 판단력, 확률적, 실제 API 필요)를 본다. 이 파일은 성격이 다르다 —
"그 판단 결과를 이전 턴의 state.feature_labels와 어떻게 합치는가"만 보는
결정론적 코드 동작 테스트라, 실제 LLM을 호출하지 않고 GPTClient.get_response를
턴마다 원하는 값으로 mock한다.

핵심 배경(weight_extractor.py 참고, 2026-09-20 병합 로직 + previous_labels 도입):
WeightExtractor.run()은 이제 이전 턴의 feature_labels를 `previous_labels` input
variable로 프롬프트에 함께 넘긴다(Extractor의 current_context와 같은 패턴). 이번 턴
결과(FeatureLabelMap)의 각 축 값은 세 가지로 갈린다:
  1. 정상 라벨(FeatureLabel 객체) — 이번 턴에 그 축을 다뤘음 → 새 값으로 병합
  2. 문자열 "cancelled" — [이전 라벨]에 있던 걸 대체 값 없이 명시적으로 취소함 → 그 축을 지움
  3. dict에 키 자체가 없음 — 이번 턴이 그 축을 아예 안 다룸 → 이전 값을 그대로 둠(병합)
이 세 갈래를 코드가 구분해서 처리하므로, "이번 턴에 안 다룸"과 "명시적으로 취소함"이
더 이상 같은 것으로 뭉개지지 않는다(이전에는 스키마에 취소 신호가 없어 둘 다 "결과에서
빠짐"으로 동일하게 와서 구분이 불가능했다 — 그 한계는 이번에 해소됐다).
"""
import asyncio
import importlib
import sys
from unittest.mock import AsyncMock, patch

from src.interfaces.schema.walk_schema import WalkMode
from src.schema.prewalk_schema import FeatureLabel, FeatureLabelMap, FeatureTag, Location, State

# conftest.py가 gpt_client를 통째로 MagicMock으로 치환해 둔다(대부분의 테스트는 LLM을
# 실제로 안 쓰니 괜찮지만, 이 파일은 WeightExtractor.run()의 실제 상태 대입 로직을
# 그대로 실행해야 해서 test_graph_repository_scores.py와 같은 방식으로 원본을 다시 불러온다.
sys.modules.pop("src.infrastructure.external.client.gpt_client", None)
sys.modules.pop("src.agent.nodes.weight_extractor", None)
GPTClient = importlib.import_module("src.infrastructure.external.client.gpt_client").GPTClient
WeightExtractor = importlib.import_module("src.agent.nodes.weight_extractor").WeightExtractor

_LOCATION = Location(lat=37.5665, lon=126.9780)


def _label(preference: str, explicitness: str) -> FeatureLabel:
    return FeatureLabel(preference_label=preference, explicitness_label=explicitness)


def _state(mode=WalkMode.CIRCULAR_RANDOM, user_prompt: str = "", feature_labels=None) -> State:
    return State(
        user_id=1,
        current_location=_LOCATION,
        mode=mode,
        user_prompt=user_prompt,
        feature_labels=feature_labels or {},
    )


def _labels(**by_tag) -> FeatureLabelMap:
    """_labels(safety=("high", "explicit_soft")) 같은 축약 표기를 FeatureLabelMap으로
    변환한다. _labels(safety="cancelled")처럼 문자열 "cancelled"를 그대로 넘기면
    취소 신호로 취급한다."""
    root = {}
    for tag, value in by_tag.items():
        root[FeatureTag(tag)] = value if value == "cancelled" else _label(*value)
    return FeatureLabelMap(root=root)


def _run_with_mock_result(extractor: WeightExtractor, state: State, result: FeatureLabelMap) -> State:
    """이번 턴 LLM이 result를 반환했다고 가정하고 실제로 run()을 돌린다(LLM 미호출)."""
    with patch.object(GPTClient, "get_response", new=AsyncMock(return_value=result)):
        return asyncio.run(extractor.run(state))


def test_second_turn_correctly_overwrites_when_axis_is_restated():
    """이번 턴이 그 축을 다시 언급하면(새 라벨이 결과에 있음) 새 값으로 정확히 바뀐다."""
    extractor = WeightExtractor()
    state = _state(feature_labels={FeatureTag.SAFETY: _label("high", "explicit_soft")})

    state = _run_with_mock_result(extractor, state, _labels(safety=("low", "explicit_soft")))

    assert state.feature_labels[FeatureTag.SAFETY].preference_label == "low"


def test_unrelated_turn_preserves_previous_label():
    """이전 턴에 설정된 라벨은, 이번 턴이 그 축을 언급하지 않으면(결과 dict에 키 자체가
    없으면) 사라지지 않고 그대로 남는다(병합) — 취소를 요청한 적이 없으므로 유지하는
    것이 맞는 동작이다."""
    extractor = WeightExtractor()
    state = _state(feature_labels={FeatureTag.SAFETY: _label("high", "explicit_soft")})

    state = _run_with_mock_result(extractor, state, _labels())  # 이번 턴은 아무 축도 언급 안 함

    assert state.feature_labels[FeatureTag.SAFETY].preference_label == "high", (
        "이전 safety 라벨이 유지돼야 한다. 이 assert가 깨지면 병합 로직이 다시 깨진 것이다."
    )


def test_explicit_cancellation_now_clears_the_axis():
    """2026-09-20부터: LLM이 그 축에 대해 문자열 "cancelled"를 반환하면 병합 로직이
    이전 값을 실제로 지운다. previous_labels를 프롬프트에 넘기기 전에는 "이번 턴에
    안 다룸"과 "명시적으로 취소함"을 구분할 방법이 없어 취소해도 이전 값이 남는 한계가
    있었는데, 이제 코드 차원에서 명확히 구분된다."""
    extractor = WeightExtractor()
    state = _state(feature_labels={FeatureTag.SAFETY: _label("high", "explicit_soft")})

    state = _run_with_mock_result(extractor, state, _labels(safety="cancelled"))

    assert FeatureTag.SAFETY not in state.feature_labels


def test_cancellation_of_one_axis_does_not_touch_the_other():
    """두 축이 모두 설정된 상태에서 safety만 취소되면, comfort는 손대지 않고 그대로
    남는다 — 취소가 다른 축까지 함께 지우면 안 된다."""
    extractor = WeightExtractor()
    state = _state(feature_labels={
        FeatureTag.SAFETY: _label("high", "explicit_soft"),
        FeatureTag.COMFORT: _label("high", "explicit_soft"),
    })

    state = _run_with_mock_result(extractor, state, _labels(safety="cancelled"))

    assert FeatureTag.SAFETY not in state.feature_labels
    assert state.feature_labels[FeatureTag.COMFORT].preference_label == "high"


def test_partial_restatement_preserves_the_axis_that_was_not_repeated():
    """두 축이 모두 설정된 상태에서 이번 턴이 comfort만 다시 언급하면, safety는 그대로
    유지되고 comfort만 새 값으로 바뀐다 — 실제 대화에서 가장 흔할 시나리오(한 축만 조정)."""
    extractor = WeightExtractor()
    state = _state(feature_labels={
        FeatureTag.SAFETY: _label("high", "explicit_soft"),
        FeatureTag.COMFORT: _label("high", "explicit_soft"),
    })

    state = _run_with_mock_result(extractor, state, _labels(comfort=("low", "explicit_soft")))

    assert state.feature_labels[FeatureTag.SAFETY].preference_label == "high"
    assert state.feature_labels[FeatureTag.COMFORT].preference_label == "low"


def test_mode_skip_preserves_labels_without_any_llm_call():
    """GPS_ART/ONEWAY_SHORTEST로 모드가 바뀌어도 LLM 호출 없이 기존 feature_labels를
    그대로 둔다(전에는 무조건 {}로 초기화했다). 사용자가 잠깐 최단경로로 바꿨다가 다시
    순환으로 돌아오면, 그 사이에 쌓인 선호가 그대로 이어진다. get_response를 mock하지
    않아도 이 경로는 애초에 LLM을 호출하지 않는다."""
    extractor = WeightExtractor()
    state = _state(
        mode=WalkMode.CIRCULAR_RANDOM,
        feature_labels={FeatureTag.SAFETY: _label("high", "explicit_soft")},
    )

    state.mode = WalkMode.ONEWAY_SHORTEST
    state = asyncio.run(extractor.run(state))

    assert state.feature_labels[FeatureTag.SAFETY].preference_label == "high"


def test_previous_labels_are_actually_sent_to_the_prompt():
    """배선 회귀 방지: run()이 get_response를 부를 때 previous_labels input variable에
    이전 state.feature_labels 기반 내용이 실제로 들어가는지 확인한다. 이게 빠지면
    LLM이 [이전 라벨]을 못 봐서 취소 신호를 낼 근거 자체가 사라진다."""
    extractor = WeightExtractor()
    state = _state(feature_labels={FeatureTag.SAFETY: _label("high", "explicit_soft")})

    mock = AsyncMock(return_value=_labels())
    with patch.object(GPTClient, "get_response", new=mock):
        asyncio.run(extractor.run(state))

    sent_variables = mock.call_args.kwargs["input_variables"]
    assert "previous_labels" in sent_variables
    assert "safety" in sent_variables["previous_labels"]
    assert "high" in sent_variables["previous_labels"]
