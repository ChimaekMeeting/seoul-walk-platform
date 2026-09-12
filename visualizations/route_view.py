"""실행 기록을 외부 연결 없는 재생 화면과 최종 경로 PNG로 출력한다."""

from __future__ import annotations

import json
import math
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D

from visualizations.network_view import EARTH_RADIUS_M, _korean_font, _local_xy, _segments_in_square


# 서비스에 연결된 엔진인지(RunConditions.service_use)를 이름에 같이 적는다. 순환·편도
# Beam은 RouteService.base_engines에 있고, GRASP 계열은 아직 서비스에 연결되지 않았다.
LABELS = {"shortest": "최단거리 · A*", "shortest_alt": "최단거리 · A* + ALT",
          "detour": "편도 우회 · Beam(서비스)", "circular": "순환 · Beam(서비스)"}
LABELS.update({f"grasp_{r}": f"GRASP + {r.upper()}(벤치마크)"
               for r in ("none", "local", "vnd", "vns", "alns")})
LABELS["grasp_none"] = "GRASP · 구축만(벤치마크)"

# 비교표 배지 문구. 값은 RunConditions.service_use가 정한다.
SERVICE_BADGES = {"service": "서비스 엔진", "benchmark_only": "벤치마크 전용"}


def event_nodes(result):
    used = {result["start"]["node"], result["end"]["node"]}
    for event in result["trace"]:
        for path in [*event.get("paths", []), *event.get("tree", [])]:
            used.update(path)
        for key in ("explored", "frontier", "before", "waypoints", "previous_waypoints", "choices"):
            used.update(event.get(key, []))
        if "current" in event:
            used.add(event["current"])
    return used


def landmark_points(result):
    """실행 조건에 기록된 ALT 랜드마크 좌표. Haversine 실행이면 빈 목록이다."""
    heuristic = (result.get("conditions") or {}).get("heuristic") or {}
    return heuristic.get("landmarks") or []


def describe_settings(result):
    """비교표에 그대로 보여 줄 실행 조건 한 줄. 끝에 서비스 연결 배지를 붙인다."""
    conditions = result.get("conditions") or {}
    badge = SERVICE_BADGES.get(conditions.get("service_use"))
    if "config" in result:
        text = f"경유지 2개 · 재시작 {result['config']['grasp_iters']}회 · seed {result['seed']}"
    else:
        heuristic = conditions.get("heuristic") or {}
        if not heuristic:
            text = ""
        elif heuristic["name"] == "haversine":
            text = "Haversine"
        else:
            text = (f"ALT {heuristic['method'].capitalize()} k={heuristic['k_requested']} "
                    f"(실제 {heuristic['k_actual']}개)")
    return " · ".join(part for part in (text, badge) if part)


def write_route_views(graph, report, output):
    origin = report["scenario"]["origin"]
    used = set().union(*(event_nodes(r) for r in report["results"]))
    points = {n: _local_xy(graph.nodes[n]["lat"], graph.nodes[n]["lon"], origin["lat"], origin["lon"])
              for n in used}
    xs, ys = zip(*points.values())
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    radius = max(max(xs) - min(xs), max(ys) - min(ys), 500) / 2 + 180
    # 기존 정사각형 자르기를 이용하되 탐색 전체가 들어오도록 표시 중심을 옮긴다.
    center_lat = origin["lat"] + math.degrees(cy / EARTH_RADIUS_M)
    center_lon = origin["lon"] + math.degrees(cx / (EARTH_RADIUS_M * math.cos(math.radians(origin["lat"]))))
    segments, _ = _segments_in_square(graph, center_lat, center_lon, radius)
    points = {n: _local_xy(graph.nodes[n]["lat"], graph.nodes[n]["lon"], center_lat, center_lon) for n in used}
    payload = {"nodes": {str(n): [round(x, 2), round(y, 2)] for n, (x, y) in points.items()},
               "background": [[[round(x, 2), round(y, 2)] for x, y in s] for s in segments],
               "radius": radius, "cases": report["intent_cases"],
               "results": [{k: r[k] for k in ("mode", "engine", "target_m", "start", "end", "metrics", "trace", "route_valid", "tolerance_ratio", "run_seconds", "keyframes", "keyframe_policy")}
                           for r in report["results"]]}
    for item, result in zip(payload["results"], report["results"]):
        coords = [points[n] for n in event_nodes(result)]
        xs, ys = zip(*coords)
        item["bounds"] = {"cx": (min(xs)+max(xs))/2, "cy": (min(ys)+max(ys))/2,
                          "radius": max(max(xs)-min(xs), max(ys)-min(ys), 400)/2+100}
        item["settings"] = describe_settings(result)
        item["conditions"] = result.get("conditions")
        # 랜드마크는 경로가 지나지 않는 외곽 노드다. 화면 범위(bounds)는 event_nodes로만
        # 잡고 여기서는 좌표만 따로 넘긴다 — 넣으면 지도가 랜드마크까지 넓어진다.
        item["landmarks"] = [[round(x, 2), round(y, 2)] for x, y in
                             (_local_xy(m["lat"], m["lon"], center_lat, center_lon)
                              for m in landmark_points(result))]
    template = Path(__file__).with_name("route_player.html").read_text(encoding="utf-8")
    serialized = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c").replace("&", "\\u0026")
    (output / "routes.html").write_text(template.replace("__ROUTE_DATA__", serialized), encoding="utf-8")
    font = _korean_font()
    rows = math.ceil(len(report["results"]) / 3)
    fig, axes = plt.subplots(rows, 3, figsize=(18, 6 * rows + 1), squeeze=False)
    colors = ("#2563eb", "#ea580c", "#15803d")
    for ax in axes.flat:
        ax.set_visible(False)
    for i, (ax, result) in enumerate(zip(axes.flat, report["results"])):
        ax.set_visible(True)
        color = colors[i % len(colors)]
        ax.add_collection(LineCollection(segments, colors="#c7cdd5", linewidths=0.45))
        for i, path in enumerate(result["paths"]):
            if path:
                x, y = zip(*(points[n] for n in path))
                ax.plot(x, y, color=color, lw=2.1 if i == 0 else 1, alpha=1 if i == 0 else 0.35)
        markers = [("start", "*", "#dc2626")]
        if result["end"]["node"] != result["start"]["node"]:
            markers.append(("end", "o", "#111827"))
        for field, marker, shade in markers:
            x, y = points[result[field]["node"]]
            ax.scatter(x, y, marker=marker, s=80, c=shade, zorder=5)
        metric = result["metrics"][0] if result["metrics"] else None
        distance = f"{metric['distance_m'] / 1000:.3f}km" if metric else "경로 없음"
        target = f" / 목표 {result['target_m'] / 1000:.3f}km" if result["target_m"] else ""
        status = "\n목표 허용 범위 벗어남" if metric and metric["target_within_tolerance"] is False else ""
        ax.set_title(f"{LABELS[result['mode']]}\n{distance}{target}{status}", fontproperties=font, fontsize=12)
        ax.set(xlim=(-radius, radius), ylim=(-radius, radius), aspect="equal")
        ax.set_xlabel("동서 거리 (m)", fontproperties=font)
        ax.set_ylabel("남북 거리 (m)", fontproperties=font)
        ax.grid(alpha=0.12)
    fig.suptitle("상명대 정문 출발 · 실제 엔진의 반환 경로", fontproperties=font, fontsize=18)
    fig.legend(handles=[Line2D([], [], marker="*", color="#dc2626", linestyle="none", label="상명대 출발·순환 복귀"),
                        Line2D([], [], marker="o", color="#111827", linestyle="none", label="경복궁역 3번 출입구")],
               loc="lower center", bbox_to_anchor=(0.5, 0.04), ncol=2, prop=font, frameon=False)
    fig.text(0.5, 0.015, "거리 기반 실험 · 재방문 억제와 기존 정리 규칙 유지 · 선은 도보망 연결도 · 탐색 과정은 routes.html에서 재생",
             ha="center", fontproperties=font, fontsize=9)
    fig.tight_layout(rect=(0, 0.15, 1, 0.91))
    fig.savefig(output / "routes.png", dpi=150, facecolor="white")
    plt.close(fig)
