"""
tests/unit/test_graph_filter.py
filter_graph_by_request 단위 테스트

담당: QA (예원)
검증 항목:
  - exclude_underground=True 이면 is_underground 노드가 제거된다
  - exclude_overpass=True 이면 is_overpass 노드가 제거된다
  - 두 옵션 모두 True이면 두 종류 노드가 모두 제거된다
  - 두 옵션 모두 False이면 아무 노드도 제거되지 않는다 (기본값)
  - 원본 그래프는 수정되지 않는다 (copy 보호)
  - 노드에 연결된 엣지도 함께 제거된다
"""

import pytest
import networkx as nx

from src.route_engine.graph.graph_filter import filter_graph_by_request

# ── 그래프 픽스처 ────────────────────────────────────────────────────────────


@pytest.fixture
def mixed_graph():
    """
    노드 구성:
      0 - 일반 노드
      1 - 지하 노드 (is_underground=True)
      2 - 고가 노드 (is_overpass=True)
      3 - 일반 노드
    엣지: 0-1, 1-2, 2-3
    """
    G = nx.Graph()
    G.add_node(0, is_underground=False, is_overpass=False)
    G.add_node(1, is_underground=True, is_overpass=False)
    G.add_node(2, is_underground=False, is_overpass=True)
    G.add_node(3, is_underground=False, is_overpass=False)
    G.add_edge(0, 1)
    G.add_edge(1, 2)
    G.add_edge(2, 3)
    return G


# ── exclude_underground ──────────────────────────────────────────────────────


class TestExcludeUnderground:
    def test_지하_노드가_제거된다(self, mixed_graph):
        result = filter_graph_by_request(mixed_graph, {"exclude_underground": True})
        assert 1 not in result.nodes

    def test_일반_노드는_유지된다(self, mixed_graph):
        result = filter_graph_by_request(mixed_graph, {"exclude_underground": True})
        assert 0 in result.nodes
        assert 3 in result.nodes

    def test_고가_노드는_유지된다(self, mixed_graph):
        result = filter_graph_by_request(mixed_graph, {"exclude_underground": True})
        assert 2 in result.nodes

    def test_지하_노드에_연결된_엣지도_제거된다(self, mixed_graph):
        result = filter_graph_by_request(mixed_graph, {"exclude_underground": True})
        assert not result.has_edge(0, 1)
        assert not result.has_edge(1, 2)


# ── exclude_overpass ─────────────────────────────────────────────────────────


class TestExcludeOverpass:
    def test_고가_노드가_제거된다(self, mixed_graph):
        result = filter_graph_by_request(mixed_graph, {"exclude_overpass": True})
        assert 2 not in result.nodes

    def test_일반_노드는_유지된다(self, mixed_graph):
        result = filter_graph_by_request(mixed_graph, {"exclude_overpass": True})
        assert 0 in result.nodes
        assert 3 in result.nodes

    def test_지하_노드는_유지된다(self, mixed_graph):
        result = filter_graph_by_request(mixed_graph, {"exclude_overpass": True})
        assert 1 in result.nodes

    def test_고가_노드에_연결된_엣지도_제거된다(self, mixed_graph):
        result = filter_graph_by_request(mixed_graph, {"exclude_overpass": True})
        assert not result.has_edge(1, 2)
        assert not result.has_edge(2, 3)


# ── 두 옵션 동시 적용 ────────────────────────────────────────────────────────


class TestExcludeBoth:
    def test_지하_고가_노드_모두_제거된다(self, mixed_graph):
        result = filter_graph_by_request(
            mixed_graph, {"exclude_underground": True, "exclude_overpass": True}
        )
        assert 1 not in result.nodes
        assert 2 not in result.nodes

    def test_일반_노드만_남는다(self, mixed_graph):
        result = filter_graph_by_request(
            mixed_graph, {"exclude_underground": True, "exclude_overpass": True}
        )
        assert set(result.nodes) == {0, 3}

    def test_남은_노드_간_엣지는_없다(self, mixed_graph):
        """0-3 사이에 직접 엣지가 없었으므로 필터 후 엣지 수 = 0."""
        result = filter_graph_by_request(
            mixed_graph, {"exclude_underground": True, "exclude_overpass": True}
        )
        assert result.number_of_edges() == 0


# ── 기본값 (필터 없음) ───────────────────────────────────────────────────────


class TestNoFilter:
    def test_기본값에서는_아무_노드도_제거되지_않는다(self, mixed_graph):
        result = filter_graph_by_request(mixed_graph, {})
        assert result.number_of_nodes() == mixed_graph.number_of_nodes()

    def test_false_명시해도_제거되지_않는다(self, mixed_graph):
        result = filter_graph_by_request(
            mixed_graph, {"exclude_underground": False, "exclude_overpass": False}
        )
        assert result.number_of_nodes() == mixed_graph.number_of_nodes()

    def test_엣지도_그대로_유지된다(self, mixed_graph):
        result = filter_graph_by_request(mixed_graph, {})
        assert result.number_of_edges() == mixed_graph.number_of_edges()


# ── 원본 그래프 보호 ─────────────────────────────────────────────────────────


class TestOriginalGraphProtection:
    def test_원본_그래프는_수정되지_않는다(self, mixed_graph):
        original_node_count = mixed_graph.number_of_nodes()
        filter_graph_by_request(
            mixed_graph, {"exclude_underground": True, "exclude_overpass": True}
        )
        assert mixed_graph.number_of_nodes() == original_node_count

    def test_반환값은_새_그래프_객체다(self, mixed_graph):
        result = filter_graph_by_request(mixed_graph, {"exclude_underground": True})
        assert result is not mixed_graph


# ── 엣지 케이스 ─────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_빈_그래프는_빈_그래프를_반환한다(self):
        G = nx.Graph()
        result = filter_graph_by_request(G, {"exclude_underground": True})
        assert result.number_of_nodes() == 0

    def test_속성이_없는_노드는_제거되지_않는다(self):
        """is_underground 속성 자체가 없는 노드는 필터 대상이 아니다."""
        G = nx.Graph()
        G.add_node(0)  # 속성 없음
        G.add_node(1, is_underground=True)
        result = filter_graph_by_request(G, {"exclude_underground": True})
        assert 0 in result.nodes
        assert 1 not in result.nodes

    def test_모든_노드가_지하이면_노드가_없는_그래프를_반환한다(self):
        G = nx.Graph()
        G.add_node(0, is_underground=True)
        G.add_node(1, is_underground=True)
        G.add_edge(0, 1)
        result = filter_graph_by_request(G, {"exclude_underground": True})
        assert result.number_of_nodes() == 0
        assert result.number_of_edges() == 0
