# 위도경도 → 기상청 격자 변환 함수 추가
import math

def latlon_to_grid(lat: float, lng: float) -> tuple[int, int]:
    """
    위도경도 → 기상청 nx, ny 격자 좌표 변환
    기상청은 자체 격자 좌표를 사용하기 때문에 반드시 변환 필요
    """
    RE = 6371.00877
    GRID = 5.0
    SLAT1, SLAT2 = 30.0, 60.0
    OLON, OLAT = 126.0, 38.0
    XO, YO = 43, 136
    DEGRAD = math.pi / 180.0

    re = RE / GRID
    slat1 = SLAT1 * DEGRAD
    slat2 = SLAT2 * DEGRAD
    olon  = OLON  * DEGRAD
    olat  = OLAT  * DEGRAD

    sn = math.log(math.cos(slat1) / math.cos(slat2))
    sn /= math.log(math.tan(math.pi * 0.25 + slat2 * 0.5) /
                   math.tan(math.pi * 0.25 + slat1 * 0.5))
    sf = math.pow(math.tan(math.pi * 0.25 + slat1 * 0.5), sn)
    sf *= math.cos(slat1) / sn
    ro = re * sf / math.pow(math.tan(math.pi * 0.25 + olat * 0.5), sn)

    ra = re * sf / math.pow(math.tan(math.pi * 0.25 + lat * DEGRAD * 0.5), sn)
    theta = lng * DEGRAD - olon
    if theta > math.pi:  theta -= 2.0 * math.pi
    if theta < -math.pi: theta += 2.0 * math.pi
    theta *= sn

    nx = int(ra * math.sin(theta) + XO + 0.5)
    ny = int(ro - ra * math.cos(theta) + YO + 0.5)
    return nx, ny


# get_environment_info 수정 — lat, lng 받도록
def get_environment_info(lat: float = 37.5665,
                         lng: float = 126.9780) -> dict:
    """
    날씨 + 대기질 통합 반환
    lat, lng: 사용자 현재 위치 (기본값: 서울시청)
    """
    # 위도경도 → 기상청 격자 변환
    nx, ny = latlon_to_grid(lat, lng)

    weather_status, weather_msg = get_weather_korea(nx, ny)
    air_status,     air_msg     = get_air_quality()

    auto_pref = (
        WEATHER_TO_PREFERENCE.get(weather_status) or
        AIR_TO_PREFERENCE.get(air_status)
    )

    return {
        "weather_status": weather_status,
        "weather_msg":    weather_msg,
        "air_status":     air_status,
        "air_msg":        air_msg,
        "auto_pref":      auto_pref,
        "display_msg":    f"{weather_msg}\n{air_msg}",
        # NLP 팀(이예니)에 전달할 데이터
        "env_data": {
            "weather":    weather_status,
            "air":        air_status,
            "auto_pref":  auto_pref,
            "lat":        lat,
            "lng":        lng,
        }
    }