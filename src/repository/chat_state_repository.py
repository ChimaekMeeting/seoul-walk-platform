from src.database.valkey import get_valkey_db
import json
from typing import Optional, Dict, Any

class ChatStateRepository:
    @staticmethod
    async def save_state(thread_id: str, state: Dict[str, Any]) -> None:
        """
        사용자의 대화 세션 상태를 Valkey에 저장합니다.

        Args:
            thread_id: 세션 식별 ID
            state: 상태 정보(extraction, interview, final_review, decision, weighting)
        """
        redis = get_valkey_db()
        key = f"chat_state:{thread_id}"

        await redis.set(key, json.dumps(state, ensure_ascii=False), ex=3600)

    @staticmethod
    async def get_state(thread_id: str) -> Optional[Dict[str, Any]]:
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
        
        return json.loads(raw_data)