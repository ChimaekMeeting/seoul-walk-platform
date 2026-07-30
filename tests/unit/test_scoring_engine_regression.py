"""
tests/unit/test_scoring_engine_regression.py
scoring_engine.calculate_custom_score의 "현재 동작"을 고정하는 회귀 테스트.

목적:
  - score/profile을 확장하거나 scoring_engine을 일반화 리팩토링하기 전에,
    지금 시점의 custom_score 계산 방향(증가/감소)을 스냅샷처럼 남긴다.
  - 정확한 수치가 아니라 "어떤 score가 높아지면 cost가 어느 방향으로 움직이는가"만 검증한다.
  - default(general) 프로파일은 src/route_engine/profiles.py의 실제 PROFILES를 사용한다.
  - child/landmark/running 가중치는 현재 모드(3개)에서 사용되지 않지만 scoring_engine은
    여전히 해당 score들을 계산하므로, 가중치를 인라인으로 구성해 방향 회귀를 고정한다.

정책:
  - slope_score는 경사도가 아니라 평탄도다. 1.0에 가까울수록 평지다.
  - 모든 모드에서 평탄도가 높을수록 cost가 낮아진다.
  - child_score 자체는 가점으로 사용하지 않고 is_vehicle_caution을 감점한다.
"""

import networkx as nx

from src.route_engine.scoring.scoring_engine import calculate_custom_score
from src.route_engine.profiles import PROFILES, ProfileConfig, ScoringProfile
from src.schema.route_schema import Weights

# ── 그래프 헬퍼 ──────────────────────────────────────────────────────────────

BASE_EDGE = {
    "length": 100.0,
    "safety_score": 0.3,
    "nature_score": 0.3,
    "slope_score": 0.3,
    "running_score": 0.3,
    "landmark_score": 0.0,
    "child_score": 0.0,
    "is_vehicle_caution": False,
    "tags": [],
}


def make_graph(edge_data: dict) -> nx.Graph:
    """단일 엣지 그래프를 생성합니다."""
    G = nx.Graph()
    G.add_node(0)
    G.add_node(1)
    G.add_edge(0, 1, **edge_data)
    return G


def score_of(G: nx.Graph) -> float:
    return G[0][1]["custom_score"]


def profile_payload(config, mode: str) -> dict:
    """ProfileConfig(profiles.py)를 calculate_custom_score가 받는 dict로 변환합니다."""
    return {
        "mode": mode,
        "weights": config.weights,
        "blocked_tags": config.blocked_tags,
    }


_CHILD    = ProfileConfig(weights=Weights(safety=1.0, nature=0.3, slope=1.0, child=1.0),    blocked_tags=["underground", "highway"])
_LANDMARK = ProfileConfig(weights=Weights(safety=0.5, nature=0.5, slope=0.3, landmark=1.0), blocked_tags=["underground"])
_RUNNING  = ProfileConfig(weights=Weights(safety=0.5, nature=0.5, slope=0.7, running=1.0),  blocked_tags=["underground"])

DEFAULT_PROFILE  = profile_payload(PROFILES[ScoringProfile.DEFAULT], mode="general")
CHILD_PROFILE    = profile_payload(_CHILD,    mode="general")
LANDMARK_PROFILE = profile_payload(_LANDMARK, mode="general")
RUNNING_PROFILE  = profile_payload(_RUNNING,  mode="running")


# ── 1. default/general profile: safety/nature/slope가 높으면 cost가 낮다 ────


class TestDefaultProfileDirection:
    def test_safety_score가_높으면_custom_score가_낮다(self):
        G_base = make_graph(BASE_EDGE)
        G_high = make_graph({**BASE_EDGE, "safety_score": 0.9})

        calculate_custom_score(G_base, DEFAULT_PROFILE)
        calculate_custom_score(G_high, DEFAULT_PROFILE)

        assert score_of(G_high) < score_of(G_base)

    def test_nature_score가_높으면_custom_score가_낮다(self):
        G_base = make_graph(BASE_EDGE)
        G_high = make_graph({**BASE_EDGE, "nature_score": 0.9})

        calculate_custom_score(G_base, DEFAULT_PROFILE)
        calculate_custom_score(G_high, DEFAULT_PROFILE)

        assert score_of(G_high) < score_of(G_base)

    def test_general_모드에서_slope_score가_높으면_custom_score가_낮다(self):
        """general 모드: slope_score는 '평탄함'을 의미하며 높을수록 평지 → cost 감소."""
        G_base = make_graph(BASE_EDGE)
        G_high = make_graph({**BASE_EDGE, "slope_score": 0.9})

        calculate_custom_score(G_base, DEFAULT_PROFILE)
        calculate_custom_score(G_high, DEFAULT_PROFILE)

        assert score_of(G_high) < score_of(G_base)


# ── 2. child profile: 차량 주의 Edge의 cost가 높다 ─────────────────────────


class TestChildProfileDirection:
    def test_vehicle_caution이면_custom_score가_높다(self):
        G_base = make_graph(BASE_EDGE)
        G_high = make_graph({**BASE_EDGE, "is_vehicle_caution": True})

        calculate_custom_score(G_base, CHILD_PROFILE)
        calculate_custom_score(G_high, CHILD_PROFILE)

        assert score_of(G_high) > score_of(G_base)


# ── 3. landmark profile: landmark_score가 높으면 cost가 낮다 ────────────────


class TestLandmarkProfileDirection:
    def test_landmark_score가_높으면_custom_score가_낮다(self):
        G_base = make_graph(BASE_EDGE)
        G_high = make_graph({**BASE_EDGE, "landmark_score": 0.9})

        calculate_custom_score(G_base, LANDMARK_PROFILE)
        calculate_custom_score(G_high, LANDMARK_PROFILE)

        assert score_of(G_high) < score_of(G_base)


# ── 4/5. running profile: running_score와 평탄도는 cost를 낮춘다 ───────────


class TestRunningProfileDirection:
    def test_running_score가_높으면_custom_score가_낮다(self):
        G_base = make_graph(BASE_EDGE)
        G_high = make_graph({**BASE_EDGE, "running_score": 0.9})

        calculate_custom_score(G_base, RUNNING_PROFILE)
        calculate_custom_score(G_high, RUNNING_PROFILE)

        assert score_of(G_high) < score_of(G_base)

    def test_running_모드에서도_slope_score가_높으면_custom_score가_낮다(self):
        G_base = make_graph(BASE_EDGE)
        G_high = make_graph({**BASE_EDGE, "slope_score": 0.9})

        calculate_custom_score(G_base, RUNNING_PROFILE)
        calculate_custom_score(G_high, RUNNING_PROFILE)

        assert score_of(G_high) < score_of(G_base)


# ── 6. blocked_tags: 포함된 edge는 inf ──────────────────────────────────────


class TestBlockedTagsDirection:
    def test_blocked_tag를_가진_edge는_custom_score가_inf다(self):
        edge = {**BASE_EDGE, "tags": ["tunnel"]}
        G = make_graph(edge)
        profile = {
            **DEFAULT_PROFILE,
            "blocked_tags": ["tunnel"],
        }

        calculate_custom_score(G, profile)

        assert score_of(G) == float("inf")
