from uuid import uuid4

from src.client.gpt_client import GPTClient
from src.client.kakao_client import KakaoClient
from src.repository.user.user_repository import UserRepository
from src.repository.chat.chat_session_repository import ChatSessionRepository
from src.repository.chat.chat_state_repository import ChatStateRepository
from src.service.weather.weather_checker import WeatherChecker
from src.service.prewalk.extractor import Extractor
from src.service.prewalk.interviewer import Interviewer
from src.service.prewalk.weight_assigner import WeightAssigner
from src.schema.prewalk_schema import ChatResponse, State, Location

class PrewalkOrchestrator:
    def __init__(self):
        self.gpt_client = GPTClient()
        self.weather_checker = WeatherChecker()
        self.kakao_client = KakaoClient()

        self.extractor = Extractor()
        self.interviewer = Interviewer()
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
        current_location = await self.kakao_client.get_address_from_coords(lat, lon)

        # 초기 상태 정의
        initial_state = State(
            user_uuid=user_uuid,
            current_location=Location(
                lat=lat,
                lon=lon,
                address=current_location.get("place_address"),
                place_name=current_location.get("place_name")
            ),
            user_context=None,
            origin_candidate=None,
            destination_candidate=None,
            weather_data=weather_data,
            user_prompt="",
            next_node="interviewer"
        )

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
        state.user_prompt = user_prompt

        # 정보 추출 -> user_context 업데이트
        state = await self.extractor.run(state)

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