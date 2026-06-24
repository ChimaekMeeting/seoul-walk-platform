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

주의:
  - slope_score는 general 모드와 running 모드에서 반대 방향으로 작동한다
    (평탄할수록: general은 cost 감소 / running은 cost 증가).
    이는 버그가 아니라 "현재 동작"이며, 옳다고 단정하지 않는다.
    정책이 확정되기 전까지 이 비대칭을 고정하기 위한 테스트이므로 임의로 수정하지 않는다.
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


# ── 2. child profile: child_score가 높으면 cost가 낮다 ──────────────────────


class TestChildProfileDirection:
    def test_child_score가_높으면_custom_score가_낮다(self):
        G_base = make_graph(BASE_EDGE)
        G_high = make_graph({**BASE_EDGE, "child_score": 0.9})

        calculate_custom_score(G_base, CHILD_PROFILE)
        calculate_custom_score(G_high, CHILD_PROFILE)

        assert score_of(G_high) < score_of(G_base)


# ── 3. landmark profile: landmark_score가 높으면 cost가 낮다 ────────────────


class TestLandmarkProfileDirection:
    def test_landmark_score가_높으면_custom_score가_낮다(self):
        G_base = make_graph(BASE_EDGE)
        G_high = make_graph({**BASE_EDGE, "landmark_score": 0.9})

        calculate_custom_score(G_base, LANDMARK_PROFILE)
        calculate_custom_score(G_high, LANDMARK_PROFILE)

        assert score_of(G_high) < score_of(G_base)


# ── 4/5. running profile: running_score는 낮추고, slope_score는 높인다 ─────


class TestRunningProfileDirection:
    def test_running_score가_높으면_custom_score가_낮다(self):
        G_base = make_graph(BASE_EDGE)
        G_high = make_graph({**BASE_EDGE, "running_score": 0.9})

        calculate_custom_score(G_base, RUNNING_PROFILE)
        calculate_custom_score(G_high, RUNNING_PROFILE)

        assert score_of(G_high) < score_of(G_base)

    def test_running_모드에서_slope_score가_높으면_custom_score가_높다(self):
        """
        현재 동작 고정용이며 정책 확정 전까지 임의 수정하지 않는다.

        general 모드와 달리 running 모드는 slope_factor = 1 + slope*slope_w를
        분자에 곱하므로, 같은 slope_score(평탄함)가 높을수록 오히려 cost가
        증가한다. 이게 의도(러닝은 경사 변화를 선호)인지 버그인지는 별도로
        팀 확인이 필요하며, 이 테스트는 그 확인 전까지 현재 수식의 동작을
        그대로 고정해서 리팩토링 시 회귀를 잡기 위한 것이다.
        """
        G_base = make_graph(BASE_EDGE)
        G_high = make_graph({**BASE_EDGE, "slope_score": 0.9})

        calculate_custom_score(G_base, RUNNING_PROFILE)
        calculate_custom_score(G_high, RUNNING_PROFILE)

        assert score_of(G_high) > score_of(G_base)


# ── 6. blocked_tags: 포함된 edge는 inf ──────────────────────────────────────


class TestBlockedTagsDirection:
    def test_blocked_tag를_가진_edge는_custom_score가_inf다(self):
        edge = {**BASE_EDGE, "tags": ["underground"]}
        G = make_graph(edge)

        calculate_custom_score(G, DEFAULT_PROFILE)

        assert score_of(G) == float("inf")
