from uuid import uuid4

from src.client.gpt_client import GPTClient
from src.client.kakao_client import KakaoClient
from src.repository.user_repository import UserRepository
from src.repository.chat_session_repository import ChatSessionRepository
from src.repository.chat_state_repository import ChatStateRepository
from src.service.weather.weather_checker import WeatherChecker
from src.service.node.extractor import Extractor
from src.service.node.interviewer import Interviewer
from src.service.node.weight_assigner import WeightAssigner
from src.schema.prewalk_schema import ChatResponse

class PrewalkOrchestrator:
    def __init__(self):
        self.gpt_client = GPTClient()
        self.weather_checker = WeatherChecker()
        self.kakao_client = KakaoClient()

        self.extractor = Extractor()
        self.interviewer = Interviewer(self.kakao_client)
        self.weight_assigner = WeightAssigner()

    async def get_init_message(self, user_uuid: str, lat: float, lon: float) -> ChatResponse:
        """
        산책 경로 추천 챗봇의 초기 메시지를 반환합니다.
        """
        # 사용자의 chat_session 생성
        user_id = UserRepository.get_id_by_uuid(user_uuid)
        thread_id = str(uuid4())
        ChatSessionRepository.save(user_id, thread_id)

        # 날씨 정보 획득
        weather_data, init_message = self.weather_checker.generate_init_message(lat, lon)
        current_location = await self.kakao_client.get_address_from_coords.ainvoke({"lat": lat, "lon": lon})

        # 초기 상태 정의
        initial_state = {
            "user_uuid": user_uuid,
            "current_location": {
                "lat": lat,
                "lon": lon,
                "address": current_location.get("place_address"),
                "place_name": current_location.get("place_name")
            },
            "origin_candidate": None,       # 출발지 후보군
            "destination_candidate": None,  # 목적지 후보군
            "user_context": {
                "is_circular": None,        # 순환 여부 (True: 순환, False: 편도)
                "origin": {
                    "lat": None,
                    "lon": None,
                    "address": None,
                    "place_name": None
                },
                "destination": {
                    "lat": None,
                    "lon": None,
                    "address": None,
                    "place_name": None
                },
                "purpose": None,            # 산책 목적
                "distance_km": 1.0,         # 산책 거리
            },
            "weather_data": weather_data,   # 실시간 기상 정보
            "is_confirmed": False,          # 요약된 산책 조건에 대한 유저의 최종 승인 여부
            "user_prompt": "",              # 유저 프롬프트
            "next_node": "interview"        # 다음 단계: "interview", "end"
        }

        # Valkey에 초기 상태 저장
        await ChatStateRepository.save_state(
            thread_id=thread_id,
            state=initial_state
        )

        return ChatResponse(
            thread_id=thread_id,
            message=init_message,
            state=initial_state
        )
       
    async def orchestrator(self, thread_id: str, user_prompt: str) -> ChatResponse:
        """
        산책 경로 추천 시스템 오케스트레이터입니다.
        """
        # state 로드
        state = await ChatStateRepository.get_state(thread_id)

        # user_prompt 업데이트
        state["user_prompt"] = user_prompt

        # user_context 업데이트
        extracted_data = await self.extractor.run(state)
        if hasattr(extracted_data, "model_dump"):
            state["user_context"] = extracted_data.model_dump()
        else:
            state["user_context"] = extracted_data

        # user_context 외 정보 업데이트
        response, state = await self.interviewer.run(state)
        
        # state 저장
        await ChatStateRepository.save_state(thread_id, state)
        
        return ChatResponse(
            thread_id=thread_id,
            message=response,
            state=state
        )
    
    async def assign_weight(self, thread_id: str):
        """
        LLM과 대화가 끝난 직후 지도 레이어별 가중치를 결정합니다.
        가중치 예) {safety: 0.3, fun: 0.2, ...}
        """
        state = await ChatStateRepository.get_state(thread_id)
        return await self.weight_assigner.run(state)