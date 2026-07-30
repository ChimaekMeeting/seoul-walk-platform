"""
tests/unit/test_scoring_engine.py
ScoringEngine(calculate_custom_score) 단위 테스트

담당: QA (예원)
검증 항목:
  - general 모드에서 custom_score가 1.0 이상이다 (Dijkstra 음수 방지)
  - running 모드에서 custom_score가 1.0 이상이다
  - blocked_tags에 해당하는 엣지는 inf로 설정된다
  - 점수가 [0,1] 범위를 벗어난 이상값(클램핑)이 공식을 역행하지 않는다
  - slope_w가 높을수록 경사 엣지의 점수가 높아진다 (페널티 증가)
  - landmark_w=0이면 landmark_score가 결과에 영향을 주지 않는다
"""

import math
import networkx as nx

from src.route_engine.scoring.scoring_engine import calculate_custom_score

# ── 그래프 헬퍼 ──────────────────────────────────────────────────────────────


def make_graph(edge_data: dict) -> nx.Graph:
    """단일 엣지 그래프를 생성합니다."""
    G = nx.Graph()
    G.add_node(0)
    G.add_node(1)
    G.add_edge(0, 1, **edge_data)
    return G


def score_of(G: nx.Graph) -> float:
    return G[0][1]["custom_score"]


DEFAULT_EDGE = {
    "length": 100.0,
    "safety_score": 0.7,
    "nature_score": 0.6,
    "slope_score": 0.3,
    "running_score": 0.5,
    "landmark_score": 0.8,
    "child_score": 0.5,
    "park_overlap_ratio": 0.0,
    "convenience_score": 0.0,
    "is_vehicle_caution": False,
    "toilet_count": 0,
    "transit_count": 0,
    "accessibility_poi_count": 0,
    "tags": [],
}

DEFAULT_PROFILE = {
    "mode": "general",
    "weights": {"safety": 0.5, "nature": 0.5, "slope": 0.5},
    "blocked_tags": [],
}


# ── 최솟값 보정 (≥ 1.0) ──────────────────────────────────────────────────────


class TestMinimumScore:
    def test_general_모드_custom_score는_1_이상이다(self):
        G = make_graph(DEFAULT_EDGE)
        calculate_custom_score(G, DEFAULT_PROFILE)
        assert score_of(G) >= 1.0

    def test_running_모드_custom_score는_1_이상이다(self):
        G = make_graph(DEFAULT_EDGE)
        profile = {
            "mode": "running",
            "weights": {"safety": 0.5, "nature": 0.5, "slope": 0.5, "running": 1.0},
            "blocked_tags": [],
        }
        calculate_custom_score(G, profile)
        assert score_of(G) >= 1.0

    def test_모든_점수가_0이어도_1_이상이다(self):
        edge = {
            **DEFAULT_EDGE,
            "safety_score": 0.0,
            "nature_score": 0.0,
            "slope_score": 0.0,
        }
        G = make_graph(edge)
        calculate_custom_score(G, DEFAULT_PROFILE)
        assert score_of(G) >= 1.0


# ── blocked_tags ─────────────────────────────────────────────────────────────


class TestBlockedTags:
    def test_blocked_tag가_포함된_엣지는_inf다(self):
        edge = {**DEFAULT_EDGE, "tags": ["underground"]}
        G = make_graph(edge)
        profile = {**DEFAULT_PROFILE, "blocked_tags": ["underground"]}
        calculate_custom_score(G, profile)
        assert score_of(G) == float("inf")

    def test_blocked_tag가_없으면_inf가_아니다(self):
        G = make_graph(DEFAULT_EDGE)
        profile = {**DEFAULT_PROFILE, "blocked_tags": ["underground"]}
        calculate_custom_score(G, profile)
        assert score_of(G) != float("inf")

    def test_여러_blocked_tag_중_하나라도_있으면_inf다(self):
        edge = {**DEFAULT_EDGE, "tags": ["highway"]}
        G = make_graph(edge)
        profile = {**DEFAULT_PROFILE, "blocked_tags": ["underground", "highway"]}
        calculate_custom_score(G, profile)
        assert score_of(G) == float("inf")

    def test_blocked_tags가_비어있으면_태그_있어도_inf가_아니다(self):
        edge = {**DEFAULT_EDGE, "tags": ["underground"]}
        G = make_graph(edge)
        calculate_custom_score(G, DEFAULT_PROFILE)
        assert score_of(G) != float("inf")


# ── 클램핑 (이상값 방지) ─────────────────────────────────────────────────────


class TestClamping:
    def test_slope_score가_1_초과해도_공식이_역행하지_않는다(self):
        """slope=1.5 → 클램핑 없으면 (2.0-1.5)^w = 0.5 → 급경사 선호 버그."""
        edge_normal = {**DEFAULT_EDGE, "slope_score": 1.0}  # 최대 경사
        edge_extreme = {**DEFAULT_EDGE, "slope_score": 1.5}  # 범위 초과

        G_normal = make_graph(edge_normal)
        G_extreme = make_graph(edge_extreme)

        profile = {
            **DEFAULT_PROFILE,
            "weights": {"safety": 0.5, "nature": 0.5, "slope": 1.0},
        }
        calculate_custom_score(G_normal, profile)
        calculate_custom_score(G_extreme, profile)

        # 클램핑 덕분에 1.5는 1.0으로 처리되어 같아야 함
        assert score_of(G_extreme) == score_of(G_normal)

    def test_safety_score가_0_미만이어도_공식이_안전하다(self):
        edge = {**DEFAULT_EDGE, "safety_score": -0.5}
        G = make_graph(edge)
        calculate_custom_score(G, DEFAULT_PROFILE)
        # inf나 음수가 되지 않아야 함
        assert math.isfinite(score_of(G))
        assert score_of(G) >= 1.0


# ── 가중치 영향 검증 ─────────────────────────────────────────────────────────


class TestWeightEffect:
    def test_slope_w가_높을수록_경사_엣지_점수가_높다(self):
        """slope_w 증가 → 경사 페널티 증가 → custom_score 증가."""
        high_slope_edge = {**DEFAULT_EDGE, "slope_score": 0.1}

        G_low = make_graph(high_slope_edge)
        G_high = make_graph(high_slope_edge)

        calculate_custom_score(
            G_low,
            {
                **DEFAULT_PROFILE,
                "weights": {"safety": 0.5, "nature": 0.5, "slope": 0.1},
            },
        )
        calculate_custom_score(
            G_high,
            {
                **DEFAULT_PROFILE,
                "weights": {"safety": 0.5, "nature": 0.5, "slope": 1.0},
            },
        )

        assert score_of(G_high) > score_of(G_low)

    def test_landmark_w가_0이면_landmark_score가_결과에_영향_없다(self):
        edge_no_landmark = {**DEFAULT_EDGE, "landmark_score": 0.0}
        edge_has_landmark = {**DEFAULT_EDGE, "landmark_score": 1.0}

        G1 = make_graph(edge_no_landmark)
        G2 = make_graph(edge_has_landmark)

        profile = {
            **DEFAULT_PROFILE,
            "weights": {"safety": 0.5, "nature": 0.5, "slope": 0.5, "landmark": 0.0},
        }
        calculate_custom_score(G1, profile)
        calculate_custom_score(G2, profile)

        assert score_of(G1) == score_of(G2)

    def test_landmark_w가_있으면_landmark_score가_높을수록_점수가_낮다(self):
        """landmark 가중치 → 분모 증가 → custom_score 감소 (선호 경로)."""
        edge_no = {**DEFAULT_EDGE, "landmark_score": 0.0}
        edge_has = {**DEFAULT_EDGE, "landmark_score": 1.0}

        G1 = make_graph(edge_no)
        G2 = make_graph(edge_has)

        profile = {
            **DEFAULT_PROFILE,
            "weights": {"safety": 0.5, "nature": 0.5, "slope": 0.5, "landmark": 1.0},
        }
        calculate_custom_score(G1, profile)
        calculate_custom_score(G2, profile)

        assert score_of(G2) < score_of(G1)

    def test_running_모드에서_running_score가_높을수록_점수가_낮다(self):
        """running_score 높음 → running_bonus 증가 → 분모 증가 → 선호 경로."""
        edge_low = {**DEFAULT_EDGE, "running_score": 0.0}
        edge_high = {**DEFAULT_EDGE, "running_score": 1.0}

        G1 = make_graph(edge_low)
        G2 = make_graph(edge_high)

        profile = {
            "mode": "running",
            "weights": {"safety": 0.5, "nature": 0.5, "slope": 0.5, "running": 1.0},
            "blocked_tags": [],
        }
        calculate_custom_score(G1, profile)
        calculate_custom_score(G2, profile)

        assert score_of(G2) < score_of(G1)

    def test_공원_중첩이_높을수록_nature_profile에서_선호한다(self):
        outside = make_graph(
            {**DEFAULT_EDGE, "nature_score": 0.0, "park_overlap_ratio": 0.0}
        )
        inside = make_graph(
            {**DEFAULT_EDGE, "nature_score": 0.0, "park_overlap_ratio": 1.0}
        )
        profile = {
            **DEFAULT_PROFILE,
            "weights": {"nature": 1.0},
        }

        calculate_custom_score(outside, profile)
        calculate_custom_score(inside, profile)

        assert score_of(inside) < score_of(outside)

    def test_상권이나_편의_POI가_있으면_convenience_profile에서_선호한다(self):
        no_convenience = make_graph(DEFAULT_EDGE)
        has_convenience = make_graph(
            {
                **DEFAULT_EDGE,
                "convenience_score": 0.8,
                "toilet_count": 1,
            }
        )
        profile = {
            **DEFAULT_PROFILE,
            "weights": {"convenience": 1.0},
        }

        calculate_custom_score(no_convenience, profile)
        calculate_custom_score(has_convenience, profile)

        assert score_of(has_convenience) < score_of(no_convenience)

    def test_접근성_POI가_있으면_accessibility_profile에서_선호한다(self):
        no_accessibility = make_graph(DEFAULT_EDGE)
        has_accessibility = make_graph(
            {**DEFAULT_EDGE, "accessibility_poi_count": 1}
        )
        profile = {
            **DEFAULT_PROFILE,
            "weights": {"accessibility": 1.0},
        }

        calculate_custom_score(no_accessibility, profile)
        calculate_custom_score(has_accessibility, profile)

        assert score_of(has_accessibility) < score_of(no_accessibility)

    def test_차량주의_Edge는_child_weight가_높을수록_회피한다(self):
        normal = make_graph(DEFAULT_EDGE)
        caution = make_graph(
            {**DEFAULT_EDGE, "is_vehicle_caution": True}
        )
        profile = {
            **DEFAULT_PROFILE,
            "weights": {"child": 0.8},
        }

        calculate_custom_score(normal, profile)
        calculate_custom_score(caution, profile)

        assert score_of(caution) > score_of(normal)

    def test_child_score_자체는_더_이상_안전_가점이_아니다(self):
        low = make_graph({**DEFAULT_EDGE, "child_score": 0.0})
        high = make_graph({**DEFAULT_EDGE, "child_score": 1.0})
        profile = {
            **DEFAULT_PROFILE,
            "weights": {"child": 1.0},
        }

        calculate_custom_score(low, profile)
        calculate_custom_score(high, profile)

        assert score_of(low) == score_of(high)

    def test_터널은_차단하지_않고_쾌적도만_감점한다(self):
        normal = make_graph(DEFAULT_EDGE)
        tunnel = make_graph({**DEFAULT_EDGE, "tags": ["tunnel"]})

        calculate_custom_score(normal, DEFAULT_PROFILE)
        calculate_custom_score(tunnel, DEFAULT_PROFILE)

        assert math.isfinite(score_of(tunnel))
        assert score_of(tunnel) > score_of(normal)


# ── 멀티 엣지 그래프 ─────────────────────────────────────────────────────────


class TestMultiEdgeGraph:
    def test_여러_엣지_모두에_custom_score가_설정된다(self):
        G = nx.Graph()
        G.add_node(0)
        G.add_node(1)
        G.add_node(2)
        G.add_edge(0, 1, **DEFAULT_EDGE)
        G.add_edge(1, 2, **{**DEFAULT_EDGE, "tags": ["underground"]})

        profile = {**DEFAULT_PROFILE, "blocked_tags": ["underground"]}
        calculate_custom_score(G, profile)

        assert "custom_score" in G[0][1]
        assert "custom_score" in G[1][2]
        assert G[0][1]["custom_score"] >= 1.0
        assert G[1][2]["custom_score"] == float("inf")

    def test_원본_그래프_엣지_데이터를_in_place로_수정한다(self):
        """calculate_custom_score는 copy 없이 전달된 그래프를 직접 수정한다."""
        G = make_graph(DEFAULT_EDGE)
        calculate_custom_score(G, DEFAULT_PROFILE)
        assert "custom_score" in G[0][1]
