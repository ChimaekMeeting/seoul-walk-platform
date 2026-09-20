"""챗봇 내부 오류가 사용자 응답이나 로그에 원문으로 노출되지 않는지 검증합니다."""

import asyncio
import importlib.util
import logging
from pathlib import Path
import sys
from unittest.mock import MagicMock

from src.interfaces.errors import SAFE_INTERNAL_ERROR_DETAIL
from src.schema.prewalk_schema import Location, State


def _load_real_interviewer_module(secret: str):
    class FailingGPTClient:
        async def get_response(self, **kwargs):
            raise RuntimeError(secret)

    gpt_module = sys.modules["src.infrastructure.external.client.gpt_client"]
    original = gpt_module.GPTClient
    gpt_module.GPTClient = FailingGPTClient
    try:
        source = Path(__file__).parents[2] / "src" / "agent" / "nodes" / "interviewer.py"
        spec = importlib.util.spec_from_file_location("_interviewer_safe_error_test", source)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        gpt_module.GPTClient = original


def test_interviewer_llm_오류는_공통_문구만_반환하고_로그에_원문을_남기지_않는다(caplog):
    secret = "upstream token=secret-llm-token"
    module = _load_real_interviewer_module(secret)
    interviewer = object.__new__(module.Interviewer)
    interviewer.prompt_utils = MagicMock()
    interviewer.str_parser = MagicMock()
    state = MagicMock(user_context=None, current_location=None, user_prompt="민감한 요청")

    with caplog.at_level(logging.ERROR):
        response = asyncio.run(interviewer._generate_response(state, "출발지"))

    assert response == SAFE_INTERNAL_ERROR_DETAIL
    assert secret not in caplog.text
    assert "RuntimeError" in caplog.text


def test_chat_state_access_token은_직렬화에서_제외된다():
    state = State(
        user_id=1,
        current_location=Location(lat=37.5, lon=127.0),
        access_token="secret-ro-udi-access-token",
    )

    assert state.access_token == "secret-ro-udi-access-token"
    assert "access_token" not in state.model_dump_for_storage()
    assert "secret-ro-udi-access-token" not in str(state.model_dump_for_storage())
