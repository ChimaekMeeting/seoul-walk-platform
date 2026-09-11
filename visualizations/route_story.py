"""경로 기록에 설명용 수치와 의미 있는 대표 장면 인덱스를 붙인다."""

from math import cos, hypot, radians


def path_metrics(graph, nodes, target, tolerance, start, end):
    if len(nodes) < 2 or not all(graph.has_edge(a, b) for a, b in zip(nodes, nodes[1:])):
        return None
    distance = repeated = 0.0
    seen = set()
    for a, b in zip(nodes, nodes[1:]):
        length = float(graph[a][b]["length"])
        distance += length
        key = frozenset((a, b))
        if key in seen:
            repeated += length
        seen.add(key)
    complete = nodes[0] == start and nodes[-1] == end
    error = abs(distance - target) if target is not None and complete else None
    return {"distance_m": distance, "repeated_edge_ratio": repeated / distance,
            "complete": complete, "target_error_m": error,
            "target_within_tolerance": error <= target * tolerance if error is not None else None}


def select_keyframes(events, limit=26):
    """일정 간격이 아닌 사건 종류·판단·실제 변화량으로 대표 장면을 고른다."""
    if not events:
        return []
    chosen = {0, len(events) - 1}
    groups = {}
    for i, event in enumerate(events):
        groups.setdefault(event["phase"], []).append(i)
    # 각 단계가 하는 일을 먼저 보존한다. 반복은 첫·마지막 대표와 큰 변화로 압축한다.
    for indexes in groups.values():
        chosen.add(indexes[0])
    # A*는 도착점까지 직선거리가 처음 25/50/75% 줄어든 때를 보여준다.
    # 시간이나 단계 수를 균등 분할하지 않으며, 이후 우회·후퇴는 전체 기록에 남는다.
    for threshold in (.25, .5, .75):
        crossing = next((i for i, e in enumerate(events) if e.get("goal_progress", -1) >= threshold), None)
        if crossing is not None:
            chosen.add(crossing)
    priorities = {"winner": 100, "refinement_done": 95, "prune": 90,
                  "vns_decision": 85, "alns_result": 85, "improved": 80,
                  "constructed": 65, "construction_failed": 60, "shake": 55,
                  "alns_accept": 50, "selection": 90, "connect": 40, "keep": 30, "astar": 25}

    def score(i):
        e = events[i]
        before, after = e.get("before_metrics"), e.get("stage_metrics")
        change = abs(before["distance_m"] - after["distance_m"]) if before and after else 0
        return (priorities.get(e["phase"], 0), change, i)

    candidates = {indexes[-1] for indexes in groups.values()}
    # 수락/기각 각각, 실제 개선과 전후 수치가 크게 달라지는 장면도 고려한다.
    for phase, indexes in groups.items():
        if phase in ("improved", "winner", "prune", "refinement_done"):
            candidates.update(indexes)
        for accepted in (True, False):
            matching = [i for i in indexes if events[i].get("accepted") is accepted]
            if matching:
                candidates.add(matching[0])
    for i in sorted(candidates - chosen, key=score, reverse=True):
        if len(chosen) >= limit:
            break
        chosen.add(i)
    # 첫 장면 종류가 예산보다 많아져도 시작·반환은 반드시 보존한다.
    if len(chosen) > limit:
        chosen = {0, len(events) - 1, *sorted(chosen - {0, len(events) - 1}, key=score, reverse=True)[:limit - 2]}
    return sorted(chosen)


def prepare_story(graph, result):
    events = result["trace"]
    for event in events:
        def measure(nodes):
            return path_metrics(graph, nodes, result["target_m"], result["tolerance_ratio"],
                                result["start"]["node"], result["end"]["node"])
        event["stage_metrics"] = measure(event.get("paths", [[]])[0]) if event.get("paths") else None
        event["before_metrics"] = measure(event.get("before", []))
        if event["phase"] == "astar":
            finish = graph.nodes[result["end"]["node"]]
            def remaining(node):
                p = graph.nodes[node]
                return hypot(p["lat"] - finish["lat"], (p["lon"] - finish["lon"]) * cos(radians(finish["lat"])))
            initial = remaining(result["start"]["node"])
            event["goal_progress"] = 1 - remaining(event["current"]) / initial if initial else 1
        if "previous_waypoints" in event and "waypoints" in event:
            previous, current = event["previous_waypoints"], event["waypoints"]
            event["waypoint_changes"] = {"removed": [n for n in previous if n not in current],
                                         "added": [n for n in current if n not in previous],
                                         "order_changed": previous != current}
        if event["phase"] == "prune":
            event["decision_reason"] = "반복 노드 사이의 짧은 구간을 기존 규칙으로 정리했습니다. 목표 오차가 줄어드는지 보고 채택하는 단계는 아닙니다."
        if event["phase"] == "shake":
            event["decision_reason"] = "다른 경로를 탐색하기 위한 교란입니다. 이 후보를 VND로 개선한 뒤 기존 경로와 비교합니다."
    result["keyframes"] = select_keyframes(events)
    result["keyframe_policy"] = "단계별 첫 장면, 마지막 상태, 수락·기각, 실제 개선과 큰 거리 변화를 우선한 최대 26개 대표 장면. 생략된 반복은 전체 기록에서 확인."
