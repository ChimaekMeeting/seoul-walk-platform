import logging

from langchain_core.output_parsers import PydanticOutputParser

from src.infrastructure.external.client.gpt_client import GPTClient
from src.agent.utils.chatbot_utils import PromptUtils
from src.schema.prewalk_schema import State, ConfirmationResult

logger = logging.getLogger(__name__)


class ConfirmationClassifier(GPTClient):
    def __init__(self):
        super().__init__()
        self.prompt_utils = PromptUtils()
        self.parser = PydanticOutputParser(pydantic_object=ConfirmationResult)

    async def run(self, state: State) -> State:
        """
        확인 질문에 대한 사용자 응답이 긍정인지 부정인지 판단합니다.
        """
        state.awaiting_confirmation = False

        input_variables = {
            "user_input":          state.user_prompt,
            "current_context":     self.prompt_utils.format_for_prompt(state.user_context),
            "format_instructions": self.parser.get_format_instructions(),
        }

        try:
            result: ConfirmationResult = await super().get_response(
                prompt_name="confirmation",
                input_variables=input_variables,
                parser=self.parser,
            )
        except Exception:
            # 판정 실패 시 정보 미완료로 간주해 interviewer가 확인 질문을 다시 생성하도록 함
            logger.exception("confirmation_classifier_llm_error")
            state.is_complete = False
            return state

        state.is_complete = result.is_positive
        logger.info(f"is_positive: {result.is_positive}")

        return state
