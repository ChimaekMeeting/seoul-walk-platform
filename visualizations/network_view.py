"""도보망과 입력 출발점·연결 노드를 정적인 PNG로 표시한다."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import networkx as nx
from matplotlib.collections import LineCollection
from matplotlib.font_manager import FontProperties
from matplotlib.lines import Line2D

from src.route_engine.engines.path_utils import PathUtils


EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class NetworkViewResult:
    selected_node_id: int
    selected_node_lat: float
    selected_node_lon: float
    connection_distance_m: float
    displayed_node_count: int
    displayed_edge_count: int
    zoom_radius_m: float


def _local_xy(lat: float, lon: float, center_lat: float, center_lon: float) -> tuple[float, float]:
    """기준점 주변 위경도를 설명용 동서·남북 거리(m)로 근사한다."""
    x = EARTH_RADIUS_M * math.cos(math.radians(center_lat)) * math.radians(lon - center_lon)
    y = EARTH_RADIUS_M * math.radians(lat - center_lat)
    return x, y


def _clip_segment(start, end, radius_m):
    """Liang–Barsky 방식으로 연결선을 표시 영역에 잘라 맞춘다."""
    sx, sy = start
    dx, dy = end[0] - sx, end[1] - sy
    enter, leave = 0.0, 1.0
    for p, q in ((-dx, sx + radius_m), (dx, radius_m - sx),
                 (-dy, sy + radius_m), (dy, radius_m - sy)):
        if p == 0:
            if q < 0:
                return None
            continue
        ratio = q / p
        if p < 0:
            enter = max(enter, ratio)
        else:
            leave = min(leave, ratio)
        if enter > leave:
            return None
    return [(sx + enter * dx, sy + enter * dy), (sx + leave * dx, sy + leave * dy)]


def _segments_in_square(
    graph: nx.Graph,
    center_lat: float,
    center_lon: float,
    radius_m: float,
) -> tuple[list[list[tuple[float, float]]], set[int]]:
    """표시 영역 안의 노드와 영역에 실제 교차하는 연결선을 집계한다."""
    xy_by_node: dict[int, tuple[float, float]] = {}
    for node_id, data in graph.nodes(data=True):
        lat = data.get("lat")
        lon = data.get("lon")
        if lat is None or lon is None:
            continue
        xy_by_node[node_id] = _local_xy(float(lat), float(lon), center_lat, center_lon)

    segments: list[list[tuple[float, float]]] = []
    displayed_nodes = {
        node for node, (x, y) in xy_by_node.items()
        if -radius_m <= x <= radius_m and -radius_m <= y <= radius_m
    }
    for start, end in graph.edges:
        start_xy = xy_by_node.get(start)
        end_xy = xy_by_node.get(end)
        if start_xy is None or end_xy is None:
            continue
        clipped = _clip_segment(start_xy, end_xy, radius_m)
        if clipped is not None:
            segments.append(clipped)
    return segments, displayed_nodes


def _korean_font() -> FontProperties:
    windows_font = Path("C:/Windows/Fonts/malgun.ttf")
    if windows_font.is_file():
        return FontProperties(fname=str(windows_font))
    return FontProperties(family="sans-serif")


def _draw_panel(
    ax,
    segments: list[list[tuple[float, float]]],
    node_xy: tuple[float, float],
    radius_m: float,
    title: str,
    font: FontProperties,
) -> None:
    ax.add_collection(
        LineCollection(
            segments,
            colors="#7C8796",
            linewidths=0.45,
            alpha=0.60,
            zorder=1,
            clip_on=True,
        )
    )
    ax.plot(
        [0.0, node_xy[0]],
        [0.0, node_xy[1]],
        color="#374151",
        linestyle="--",
        linewidth=1.2,
        zorder=3,
    )
    ax.scatter([0.0], [0.0], marker="*", s=190, color="#DC2626", edgecolor="white", zorder=7)
    ax.scatter(
        [node_xy[0]],
        [node_xy[1]],
        marker="o",
        s=120,
        facecolor="none",
        edgecolor="#2563EB",
        linewidth=2.3,
        zorder=6,
    )
    ax.annotate(
        "정문 입력점",
        (0.0, 0.0),
        xytext=(8, 8),
        textcoords="offset points",
        fontproperties=font,
        fontsize=9,
        color="#991B1B",
        zorder=6,
    )
    ax.annotate(
        "선택 도보망 노드",
        node_xy,
        xytext=(8, -15),
        textcoords="offset points",
        fontproperties=font,
        fontsize=9,
        color="#1E3A8A",
        zorder=6,
    )
    ax.set_xlim(-radius_m, radius_m)
    ax.set_ylim(-radius_m, radius_m)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(color="#D1D5DB", linewidth=0.5, alpha=0.5)
    ax.set_title(title, fontproperties=font, fontsize=13, pad=10)
    ax.set_xlabel("동서 거리 (m)", fontproperties=font)
    ax.set_ylabel("남북 거리 (m)", fontproperties=font)


def render_network_view(
    graph: nx.Graph,
    *,
    origin_lat: float,
    origin_lon: float,
    view_radius_m: float,
    output_path: str | Path,
    data_version: str,
) -> NetworkViewResult:
    """정문 주변 도보망과 선택 노드를 두 개의 축으로 그린다."""
    utils = PathUtils(graph)
    selected = utils.find_nearest_node_with_expansion(origin_lat, origin_lon)
    if selected is None:
        raise ValueError("정문 좌표의 300m 안에서 연결 가능한 도보망 노드를 찾지 못했습니다.")

    selected_data = graph.nodes[selected]
    selected_lat = float(selected_data["lat"])
    selected_lon = float(selected_data["lon"])
    connection_distance_m = utils._haversine_m(origin_lat, origin_lon, selected_lat, selected_lon)
    node_xy = _local_xy(selected_lat, selected_lon, origin_lat, origin_lon)
    zoom_radius_m = max(250.0, abs(node_xy[0]) * 1.25, abs(node_xy[1]) * 1.25)

    overview_segments, overview_nodes = _segments_in_square(
        graph, origin_lat, origin_lon, view_radius_m
    )
    zoom_segments, _ = _segments_in_square(graph, origin_lat, origin_lon, zoom_radius_m)
    if not overview_segments:
        raise ValueError("지정한 표시 범위에 도보망 연결이 없습니다.")

    font = _korean_font()
    fig, axes = plt.subplots(1, 2, figsize=(15, 9))
    # 전체 제목·범례·패널 제목을 위한 공간을 각각 확보한다.
    fig.subplots_adjust(left=0.07, right=0.98, bottom=0.13, top=0.76, wspace=0.23)
    _draw_panel(
        axes[0], overview_segments, node_xy, view_radius_m, f"주변 도보망 (±{view_radius_m:,.0f}m)", font
    )
    _draw_panel(
        axes[1], zoom_segments, node_xy, zoom_radius_m, f"정문 연결 확대 (±{zoom_radius_m:,.0f}m)", font
    )

    handles = [
        Line2D([0], [0], color="#7C8796", lw=2, label="도보망 연결"),
        Line2D([0], [0], marker="*", color="none", markerfacecolor="#DC2626", markersize=12, label="정문 입력점"),
        Line2D(
            [0], [0], marker="o", color="none", markerfacecolor="none",
            markeredgecolor="#2563EB", markeredgewidth=2, markersize=8, label="선택 도보망 노드",
        ),
        Line2D([0], [0], color="#374151", lw=1.2, linestyle="--", label="연결 거리"),
    ]
    fig.legend(handles=handles, loc="upper center", ncol=4, prop=font, bbox_to_anchor=(0.5, 0.86))
    fig.suptitle(
        f"상명대학교 서울캠퍼스 정문 도보망 연결\n"
        f"연결 거리 {connection_distance_m:.1f}m · 데이터 {data_version}",
        fontproperties=font,
        fontsize=16,
        y=0.98,
    )
    fig.text(
        0.5,
        0.04,
        "노드 연결도이며 실제 도로의 곡선 형태는 생략했습니다. 화면상의 선 길이는 경로 거리 계산에 사용하지 않습니다.",
        ha="center",
        fontproperties=font,
        fontsize=9,
        color="#4B5563",
    )

    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    return NetworkViewResult(
        selected_node_id=int(selected),
        selected_node_lat=selected_lat,
        selected_node_lon=selected_lon,
        connection_distance_m=connection_distance_m,
        displayed_node_count=len(overview_nodes),
        displayed_edge_count=len(overview_segments),
        zoom_radius_m=zoom_radius_m,
    )
