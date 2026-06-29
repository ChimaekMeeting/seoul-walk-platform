import logging
from langchain_core.output_parsers import StrOutputParser

from src.infrastructure.external.client.gpt_client import GPTClient
from src.agent.utils.chatbot_utils import PromptUtils
from src.schema.prewalk_schema import State

logger = logging.getLogger(__name__)

_REJECT_RESPONSE = "알겠어요. 어떤 부분을 바꿀까요? 출발지, 목적지, 거리 중 원하는 내용을 다시 알려주세요."
_PROCEED_RESPONSE = "경로를 생성하고 있어요. 잠시만 기다려주세요 🗺️"
_RETRY_RESPONSE = "음, 잘 이해하지 못했어요 😊 말씀하신 경로로 진행할까요? 바꾸고 싶은 부분이 있으면 알려주세요."


class Confirmer(GPTClient):
    """
    "이 경로로 진행할까요?" 확인 질문에 대한 사용자의 응답을
    Y(긍정) / U(수정) / N(거부) / C(불분명·잡담)로 분류하는 노드.
    """

    def __init__(self):
        super().__init__()
        self.prompt_utils = PromptUtils()
        self.str_parser   = StrOutputParser()

    async def run(self, state: State) -> State:
        try:
            raw = await super().get_response(
                prompt_name="confirm",
                input_variables={
                    "user_input":      state.user_prompt,
                    "current_context": self.prompt_utils.format_for_prompt(state.user_context),
                },
                parser=self.str_parser,
            )
            decision = self._parse_decision(raw)
        except Exception:
            logger.exception("confirmer_llm_error")
            decision = "C"  # 분류 실패 시 확인 질문을 다시 던짐

        state.confirm_decision = decision
        logger.info(f"confirm_decision: {decision}")

        if decision == "Y":
            # 긍정 → route_result 노드에서 경로 생성
            state.awaiting_confirmation = False
            state.is_complete           = True
            state.response              = _PROCEED_RESPONSE
        elif decision == "U":
            # 수정 → extractor가 user_prompt를 다시 처리하여 user_context 갱신
            state.awaiting_confirmation = False
            state.is_complete           = False
        elif decision == "N":
            # 거부 → 바로 종료되므로 여기서 안내 메시지를 직접 세팅
            state.awaiting_confirmation = False
            state.is_complete           = False
            state.route_result          = None
            state.response              = _REJECT_RESPONSE
        else:
            # C: 불분명·잡담 → 확인 대기를 유지하고 확인 질문을 다시 던짐
            # (awaiting_confirmation=True 유지 → 다음 턴도 confirmer로 진입)
            state.awaiting_confirmation = True
            state.is_complete           = False
            state.response              = _RETRY_RESPONSE

        return state

    @staticmethod
    def _parse_decision(raw: str) -> str:
        """
        LLM 출력에서 Y / U / N / C 중 하나를 추출합니다. 판단 불가 시 C(재확인).
        """
        text = (raw or "").strip().upper()
        for decision in ("Y", "U", "N", "C"):
            if decision in text:
                return decision
        return "C"
