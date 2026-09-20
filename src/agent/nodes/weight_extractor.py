import logging

from langchain_core.output_parsers import PydanticOutputParser

from src.agent.utils.chatbot_utils import PromptUtils
from src.schema.prewalk_schema import State, FeatureTag, FeatureLabelMap
from src.interfaces.schema.walk_schema import WalkMode
from src.infrastructure.external.client.gpt_client import GPTClient

logger = logging.getLogger(__name__)


class WeightExtractor(GPTClient):
    def __init__(self):
        super().__init__()
        self.parser = PydanticOutputParser(pydantic_object=FeatureLabelMap)
        self.prompt_utils = PromptUtils()

    async def run(self, state: State) -> State:
        """
        발화에서 feature별 가중치 라벨(preference_label/explicitness_label)을 추출합니다.

        이전 턴의 라벨([이전 라벨])을 프롬프트에 함께 넘겨, 이번 턴이 그 축을 명시적으로
        취소하면("cancelled") 그 축을 지우고, 다시 언급하면 새 라벨로 바꾸고, 아예 다루지
        않으면 이전 값을 그대로 둔다(병합) — "이번 턴에 안 다룸"과 "명시적으로 취소함"을
        구분하기 위한 구조다(Extractor의 current_context와 같은 패턴).
        """
        # GPS Art·최단경로는 custom_weights를 쓰지 않으므로 불필요한 LLM 호출을 건너뜀.
        # feature_labels는 건드리지 않는다 — 다른 모드로 돌아왔을 때 그대로 이어지도록.
        if state.mode in (WalkMode.GPS_ART, WalkMode.ONEWAY_SHORTEST):
            return state

        input_variables = {
            "user_input":          state.user_prompt,
            "feature_tags":        [tag.value for tag in FeatureTag],
            "previous_labels":     self.prompt_utils.format_for_prompt(state.feature_labels or None),
            "format_instructions": self.parser.get_format_instructions(),
        }

        try:
            result: FeatureLabelMap = await super().get_response(
                prompt_name     = "weight_extraction",
                input_variables = input_variables,
                parser          = self.parser,
            )
        except Exception:
            logger.exception("weight_extractor_llm_error")
            return state

        merged = dict(state.feature_labels)
        for tag, value in result.root.items():
            if value == "cancelled":
                merged.pop(tag, None)
            else:
                merged[tag] = value
        state.feature_labels = merged
        logger.info(f"feature_labels: {state.feature_labels}")

        return state
