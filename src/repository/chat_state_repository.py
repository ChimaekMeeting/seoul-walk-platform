import json
from typing import Optional

from src.database.valkey import get_valkey_db
from src.schema.prewalk_schema import State
from src.service.prewalk.chatbot_utils import PydanticUtils

class ChatStateRepository:
    @staticmethod
    async def save_state(thread_id: str, state: State) -> None:
        """
        사용자의 대화 세션 상태를 Valkey에 저장합니다.

        Args:
            thread_id: 세션 식별 ID
            state: 상태 정보(extraction, interview, final_review, decision, weighting)
        """
        redis = get_valkey_db()
        key = f"chat_state:{thread_id}"

        state = PydanticUtils.dump(state)
        json_data = json.dumps(state, ensure_ascii=False)

        await redis.set(key, json_data, ex=3600)

    @staticmethod
    async def get_state(thread_id: str) -> Optional[State]:
        """
        세션 ID에 해당하는 대화 상태를 Valkey에서 조회하여 반환합니다.

        Args:
            thread_id: 세션 식별 ID            
        """
        redis = get_valkey_db()
        key = f"chat_state:{thread_id}"

        raw_data = await redis.get(key)
        if not raw_data:
            return None
        
        raw_state = json.loads(raw_data)
        return State.model_validate(raw_state)