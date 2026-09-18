import logging

from langchain_core.output_parsers import PydanticOutputParser

from src.schema.prewalk_schema import State, FeatureTag, FeatureLabelMap
from src.interfaces.schema.walk_schema import WalkMode
from src.infrastructure.external.client.gpt_client import GPTClient

logger = logging.getLogger(__name__)


class WeightExtractor(GPTClient):
    def __init__(self):
        super().__init__()
        self.parser = PydanticOutputParser(pydantic_object=FeatureLabelMap)

    async def run(self, state: State) -> State:
        """
        발화에서 feature별 가중치 라벨(preference_label/explicitness_label)을 추출합니다.
        """
        # GPS Art·최단경로는 custom_weights를 쓰지 않으므로 불필요한 LLM 호출을 건너뜀
        if state.mode in (WalkMode.GPS_ART, WalkMode.ONEWAY_SHORTEST):
            state.feature_labels = {}
            return state

        input_variables = {
            "user_input":          state.user_prompt,
            "feature_tags":        [tag.value for tag in FeatureTag],
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

        state.feature_labels = result.root
        logger.info(f"feature_labels: {state.feature_labels}")

        return state
