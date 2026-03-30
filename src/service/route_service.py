# src/service/route_service.py
import networkx as nx
from src.repository.graph_repository import load_graph_near
from src.service.path_finder import find_route

# ─────────────────────────────────────────
# Intent → 가중치 조정
# ─────────────────────────────────────────

INTENT_WEIGHT_MAP = {
    "safe":    {"safety_score": 2.0, "slope_score": 1.0},  # 가로등 + CCTV 밀도 중시
    "nature":  {"safety_score": 1.0, "slope_score": 2.0},  # 공원 + 가로수길 선호
    "default": {"safety_score": 1.0, "slope_score": 1.0},  # 균등
}

def apply_intent_weights(G: nx.DiGraph, intent: dict) -> nx.DiGraph:
    """
    Intent에 따라 엣지 가중치를 동적으로 조정하고
    'custom_score' 키로 저장

    가중치 공식:
        custom_score = length / (safety_score^a * slope_score^b)
        → custom_score 낮을수록 알고리즘이 선호하는 엣지

    Args:
        G: 원본 그래프
        intent: {"intent": "safe", "prefer": [...], "distance_km": 3.0}
    """
    intent_type = intent.get("intent", "default")
    weight_map = INTENT_WEIGHT_MAP.get(intent_type, INTENT_WEIGHT_MAP["default"])

    safety_w = weight_map["safety_score"]
    slope_w  = weight_map["slope_score"]

    for u, v, data in G.edges(data=True):
        length      = data.get("length", 1.0) or 1.0
        safety      = data.get("safety_score", 1.0) or 1.0
        slope       = data.get("slope_score", 1.0) or 1.0

        # 점수 높을수록 선호 → 분모에 올려서 custom_score 낮춤
        custom_score = length / ((safety ** safety_w) * (slope ** slope_w) + 1e-6)
        G[u][v]["custom_score"] = custom_score

    return G


# ─────────────────────────────────────────
# 메인 서비스 함수
# ─────────────────────────────────────────

def get_route(
    start_lat: float,
    start_lng: float,
    intent: dict,
    end_lat: float = None,
    end_lng: float = None,
) -> dict:
    """
    경로 추천 메인 함수 (app.py에서 호출)

    Args:
        start_lat, start_lng: 출발 위경도
        intent: 사용자 프롬프트에서 추출한 의도가 담긴 JSON
            예) {"intent": "safe", "prefer": ["park"], "distance_km": 3.0}
        end_lat, end_lng: 도착 위경도 (없으면 순환 경로)

    Returns:
        {
            "mode": "random_walk" | "dijkstra",
            "coordinates": [[lat, lng], ...],
            "total_distance_km": float
        }
    """
    distance_km = intent.get("distance_km", 3.0)
    radius_m = distance_km * 1000 * 1.5  # 목표 거리의 1.5배 반경으로 그래프 로드

    # 1. DB에서 그래프 로드
    G = load_graph_near(start_lat, start_lng, radius_m=radius_m)

    print(f"노드 수: {G.number_of_nodes()}")  # ← 추가
    print(f"엣지 수: {G.number_of_edges()}")  # ← 추가

    if G.number_of_nodes() == 0:
        return {"mode": None, "coordinates": [], "total_distance_km": 0.0, "error": "해당 위치 근처 경로 데이터 없음"}

    # 2. Intent 기반 가중치 조정
    G = apply_intent_weights(G, intent)

    # 3. 알고리즘 실행
    result = find_route(
        G=G,
        start_lat=start_lat,
        start_lng=start_lng,
        intent=intent,
        end_lat=end_lat,
        end_lng=end_lng,
    )
    print(f"결과: {result}")

    return result