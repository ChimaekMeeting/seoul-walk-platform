"""
tests/unit/test_weight_extractor_state.py

WeightExtractor.run()이 여러 턴에 걸쳐 state.feature_labels를 어떻게 다루는지 검증한다.

scripts/eval_weight_extraction.py는 "발화 하나를 주면 LLM이 라벨을 정확히 뽑는가"
(프롬프트 판단력, 확률적, 실제 API 필요)를 본다. 이 파일은 성격이 다르다 —
"그 판단 결과를 이전 턴의 state.feature_labels와 어떻게 합치는가"만 보는
결정론적 코드 동작 테스트라, 실제 LLM을 호출하지 않고 GPTClient.get_response를
턴마다 원하는 값으로 mock한다.

핵심 배경(weight_extractor.py 참고): WeightExtractor.run()은 이전 턴의
feature_labels를 프롬프트에 전혀 넘기지 않고(Extractor의 current_context와
다르게 이번 턴 user_prompt만 봄), 결과가 나오면 `state.feature_labels =
result.root`로 통째로 교체한다(병합 아님). 그래서 이번 턴 발화가 어떤 축을
언급하지 않으면 — LLM이 정확히 "이번엔 그 얘기 없음"으로 {}를 반환했더라도 —
이전 턴에 쌓인 그 축의 라벨은 조용히 사라진다. 사용자가 취소를 요청했는지와
무관하게 똑같이 사라진다는 점, 그리고 GPS Art/최단경로로 잠깐 모드가 바뀌기만
해도 LLM 호출 없이 무조건 초기화된다는 점을 이 파일이 재현·고정한다.

이 테스트들은 "버그가 없다"를 확인하는 게 아니라 "지금 동작이 이렇다"를
고정해 둔다 — 병합 로직을 넣기로 결정하면, 이 파일의 assert들(특히 사라짐을
확인하는 쪽)을 먼저 고쳐야 한다.
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
    """_labels(safety=("high", "explicit_soft")) 같은 축약 표기를 FeatureLabelMap으로 변환."""
    root = {FeatureTag(tag): _label(*pair) for tag, pair in by_tag.items()}
    return FeatureLabelMap(root=root)


def _run_with_mock_result(extractor: WeightExtractor, state: State, result: FeatureLabelMap) -> State:
    """이번 턴 LLM이 result를 반환했다고 가정하고 실제로 run()을 돌린다(LLM 미호출)."""
    with patch.object(GPTClient, "get_response", new=AsyncMock(return_value=result)):
        return asyncio.run(extractor.run(state))


def test_second_turn_correctly_overwrites_when_axis_is_restated():
    """정상 동작 기준선: 이번 턴이 그 축을 다시 언급하면 새 값으로 정확히 바뀐다."""
    extractor = WeightExtractor()
    state = _state(feature_labels={FeatureTag.SAFETY: _label("high", "explicit_soft")})

    state = _run_with_mock_result(extractor, state, _labels(safety=("low", "explicit_soft")))

    assert state.feature_labels[FeatureTag.SAFETY].preference_label == "low"


def test_unrelated_turn_silently_wipes_previous_label():
    """이전 턴에 설정된 라벨이, 이번 턴이 그 축을 언급하지 않았을 뿐인데도 사라진다.
    사용자는 취소를 요청한 적이 없다 — LLM이 '이번 발화엔 안전 얘기가 없다({})'고
    정확히 판단해도, state.feature_labels가 통째로 교체되면서 이전 값이 함께 사라진다."""
    extractor = WeightExtractor()
    state = _state(feature_labels={FeatureTag.SAFETY: _label("high", "explicit_soft")})

    state = _run_with_mock_result(extractor, state, _labels())  # 이번 턴은 아무 축도 언급 안 함

    assert state.feature_labels == {}, (
        "현재 동작은 이전 safety 라벨이 사라지는 것이다. 이 assert가 깨지면(즉 safety가 "
        "남아있으면) 병합 로직이 이미 들어간 것이니 이 테스트를 그에 맞게 고쳐야 한다."
    )


def test_explicit_cancellation_produces_the_same_wipe_as_silence():
    """'없던 걸로 해주세요'(명시적 취소)와 그냥 언급 안 한 것이 코드 차원에서는 구분되지
    않는다 — 둘 다 LLM이 {}를 반환하고, 둘 다 같은 방식으로 지워진다. 취소 의도를
    구분해서 처리하고 싶다면 이 지점(state.feature_labels 대입부)에 별도 로직이
    필요하다는 근거 테스트다."""
    extractor = WeightExtractor()

    state_after_silence = _run_with_mock_result(
        extractor,
        _state(feature_labels={FeatureTag.SAFETY: _label("high", "explicit_soft")}),
        _labels(),
    )
    state_after_cancel = _run_with_mock_result(
        extractor,
        _state(feature_labels={FeatureTag.SAFETY: _label("high", "explicit_soft")}),
        _labels(),
    )

    assert state_after_silence.feature_labels == state_after_cancel.feature_labels == {}


def test_partial_restatement_drops_the_axis_that_was_not_repeated():
    """두 축이 모두 설정된 상태에서 이번 턴이 comfort만 다시 언급하면, safety는 사용자가
    아무 말도 안 했는데 함께 사라진다 — 실제 대화에서 가장 흔할 시나리오(한 축만 조정)."""
    extractor = WeightExtractor()
    state = _state(feature_labels={
        FeatureTag.SAFETY: _label("high", "explicit_soft"),
        FeatureTag.COMFORT: _label("high", "explicit_soft"),
    })

    state = _run_with_mock_result(extractor, state, _labels(comfort=("low", "explicit_soft")))

    assert FeatureTag.SAFETY not in state.feature_labels
    assert state.feature_labels[FeatureTag.COMFORT].preference_label == "low"


def test_mode_skip_wipes_labels_even_without_any_llm_call():
    """GPS_ART/ONEWAY_SHORTEST로 모드가 바뀌면 LLM 호출 자체를 건너뛰고 무조건 {}로
    초기화한다(weight_extractor.py 예외1). 사용자가 잠깐 최단경로로 바꿨다가 다시
    순환으로 돌아와도, 그 사이에 쌓인 선호는 이미 사라진 뒤라 복구되지 않는다.
    get_response를 mock하지 않아도 이 경로는 애초에 LLM을 호출하지 않는다."""
    extractor = WeightExtractor()
    state = _state(
        mode=WalkMode.CIRCULAR_RANDOM,
        feature_labels={FeatureTag.SAFETY: _label("high", "explicit_soft")},
    )

    state.mode = WalkMode.ONEWAY_SHORTEST
    state = asyncio.run(extractor.run(state))

    assert state.feature_labels == {}
