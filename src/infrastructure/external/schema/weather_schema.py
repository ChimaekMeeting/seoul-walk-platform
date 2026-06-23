from pydantic import BaseModel


class EnvironmentInfo(BaseModel):
    """
    날씨와 대기질 조회 결과를 나타냅니다.
    """
    weather: dict = {}  # get_weather() 반환값 (기온, 습도, 강수형태 등)
    air: dict = {}      # get_air_quality() 반환값 (미세먼지, 통합대기환경지수 등)
