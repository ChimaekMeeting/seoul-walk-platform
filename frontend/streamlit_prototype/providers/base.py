"""
frontend/streamlit_prototype/providers/base.py

환경 데이터(날씨·대기질) 조회를 위한 추상 인터페이스 정의

EnvData dataclass와 EnvProvider ABC를 포함
구현체는 providers/weather_api.py의 WeatherEnvProvider
ABC : ABstact Class (추상 클래스)
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class EnvData:
    # 날씨 상태·메시지, 대기질 상태·메시지를 담는 dataclass
    weather_status: str
    weather_msg:    str
    air_status:     str
    air_msg:        str


class EnvProvider(ABC):
    """
    환경 데이터 조회를 위한 추상 기반 클래스
    fetch(), get_banners() 구현 필수
    """
    @abstractmethod
    def fetch(self, lat: float, lng: float) -> EnvData: ...
    """
    input : lat (float), lng (float)
    output: EnvData

    위경도 기반으로 환경 데이터를 조회
    """

    @abstractmethod
    def get_banners(self, env: EnvData) -> list: ...
    """
    input : env (EnvData)
    output: list

    EnvData를 기반으로 배너 리스트를 반환한다.
    """