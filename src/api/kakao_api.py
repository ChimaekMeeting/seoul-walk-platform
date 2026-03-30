import os
import requests
from dotenv import load_dotenv, find_dotenv

# 환경변수 로드
load_dotenv(find_dotenv(), override=True)
KAKAO_KEY = os.getenv("KAKAO_REST_API_KEY")


def get_kakao_places_page(
    lat, lon, page=1, radius=2000, category_code=None, keyword=None
):
    """
    카카오 로컬 API를 통해 주변 장소(카테고리/키워드) 데이터를 가져옵니다.
    """
    if not KAKAO_KEY:
        return None

    is_keyword = bool(keyword)
    url = (
        "https://dapi.kakao.com/v2/local/search/keyword.json"
        if is_keyword
        else "https://dapi.kakao.com/v2/local/search/category.json"
    )
    headers = {"Authorization": f"KakaoAK {KAKAO_KEY}"}

    # API 요청 파라미터 설정
    params = {"y": lat, "x": lon, "radius": radius, "page": page, "size": 15}
    if is_keyword:
        params["query"] = keyword
    else:
        params["category_group_code"] = category_code

    try:
        response = requests.get(url, headers=headers, params=params, timeout=5)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"⚠️ 카카오 장소 검색 실패: {e}")
    return None


def get_kakao_geocode(address):
    """
    텍스트 주소를 위경도 좌표[x, y]로 변환합니다.
    """
    if not KAKAO_KEY or not address:
        return None

    url = "https://dapi.kakao.com/v2/local/search/address.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_KEY}"}
    params = {"query": address}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=3)
        if response.status_code == 200:
            docs = response.json().get("documents")
            if docs:
                return [float(docs[0]["x"]), float(docs[0]["y"])]
    except Exception as e:
        print(f"⚠️ 카카오 지오코딩 실패: {e}")
    return None
