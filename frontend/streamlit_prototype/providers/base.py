from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class EnvData:
    weather_status: str
    weather_msg:    str
    air_status:     str
    air_msg:        str


class EnvProvider(ABC):

    @abstractmethod
    def fetch(self, lat: float, lng: float) -> EnvData: ...

    @abstractmethod
    def get_banners(self, env: EnvData) -> list: ...
