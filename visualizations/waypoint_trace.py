"""GRASP와 정제 함수의 실제 선택·변경 상태를 읽는다."""
import ast
from dataclasses import asdict

from src.route_engine.engines import grasp_waypoint_common as common
from src.route_engine.engines import waypoint_local_search as local
from src.route_engine.engines import waypoint_refinement as refine
from src.route_engine import waypoint_alns as alns
from src.route_engine.engines.path_utils import PathUtils
from visualizations.route_trace import SearchTrace, _statement_line


def objective_decision(candidate, baseline):
    """실제 비교에 쓰인 RouteObjective를 설명한다. 탐색·난수 호출은 없다."""
    accepted = candidate.sort_key() < baseline.sort_key()
    if candidate.feasible != baseline.feasible:
        reason = "목표 허용 범위 충족 여부가 우선입니다."
    elif candidate.feasible:
        reason = "둘 다 목표 범위 안이므로 재통행 비율, 거리 오차 순으로 비교합니다."
    else:
        reason = "둘 다 목표 범위 밖이므로 거리 오차, 재통행 비율 순으로 비교합니다."
    if candidate.sort_key() == baseline.sort_key():
        reason += " 평가값이 같아 기존 경로를 유지합니다."
    return {"accepted": accepted, "decision_reason": reason,
            "objective_before": asdict(baseline), "objective_after": asdict(candidate)}


class WaypointTrace(SearchTrace):
    def __init__(self, engine):
        self.engine = engine
        self.events, self.codes, self.source_hashes = [], {}, {}
        self.pops = self.iterations = self.candidates_seen = 0
        self.pending = {}
        self.choice_positions = {}
        self.rules = {}
        for fn in refine.REFINEMENT_REGISTRY.values():
            self._register(fn, "refinement")
        self._register(common.construct_initial_route, "construct")
        self._register(refine._shake, "shake")
        self._register(alns._destroy, "destroy")
        self._register(alns._repair, "repair")
        self._register(alns._accept, "accept")
        self._register(refine.alns, "alns_result")
        self._register(PathUtils.prune_dead_ends, "prune")
        self._rule(common.construct_initial_route, "choice", lambda n: isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "step_d" for t in n.targets))
        for fn in (local.local_search, refine.vnd):
            self._rule(fn, "neighbor", lambda n: isinstance(n, ast.If)
                       and ast.unparse(n.test) == "better(neighbor_obj, best_neighbor_obj)")
            self._rule(fn, "improved", lambda n: isinstance(n, ast.Assign)
                       and any(isinstance(t, ast.Tuple) and ast.unparse(t) == "(current, current_obj)" for t in n.targets))
        self._rule(type(engine).find_path, "winner", lambda n: isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Tuple) and ast.unparse(t) == "(best_obj, best_route)" for t in n.targets))
        self._rule(refine.vns_loop, "vns_decision", lambda n: isinstance(n, ast.If)
                   and ast.unparse(n.test) == "better(candidate_obj, current_obj)")

    def _rule(self, fn, kind, predicate):
        if fn.__code__ not in self.codes:
            self._register(fn, "state")
        self.rules.setdefault(fn.__code__, {})[_statement_line(fn, predicate)] = kind

    def route(self, phase, route, **values):
        if route is not None:
            self._record(phase, [route.node_ids], waypoints=list(route.waypoints),
                         distance_m=route.distance_m, **values)

    def _trace(self, frame, event, arg):
        spec = self.codes.get(frame.f_code)
        if spec is None:
            return None
        v = frame.f_locals
        kind = spec[0]
        if kind == "prune" and v.get("self") is not self.engine.utils:
            return None
        key = id(frame)
        if key in self.pending and event in ("line", "return"):
            phase, details = self.pending.pop(key)
            self.route(phase, v.get("current") if phase == "improved" else v.get("best_route"), **details)
        if event == "line":
            rule = self.rules.get(frame.f_code, {}).get(frame.f_lineno)
            if rule in ("improved", "winner"):
                old = v.get("current") if rule == "improved" else v.get("best_route")
                details = {"before": list(old.node_ids) if old else [],
                           "previous_waypoints": list(old.waypoints) if old else []}
                if old is not None:
                    details.update(objective_decision(v["best_neighbor_obj"] if rule == "improved" else v["obj"],
                                                     v["current_obj"] if rule == "improved" else v["best_obj"]))
                else:
                    details.update(accepted=True, decision_reason="첫 유효 경로를 전체 최선 후보로 등록했습니다.")
                self.pending[key] = (rule, details)
            elif rule == "vns_decision":
                self.route("vns_decision", v["candidate"], before=list(v["current"].node_ids),
                           previous_waypoints=list(v["current"].waypoints), shake_level=v["shake_level"],
                           **objective_decision(v["candidate_obj"], v["current_obj"]))
            elif rule == "choice":
                # 삼항식의 다른 분기로 같은 소스 줄이 다시 실행돼도 선택 1회만 기록한다.
                if self.choice_positions.get(key) != v["i"]:
                    self.choice_positions[key] = v["i"]
                    self._record("grasp_choice", waypoints=[*v["waypoints"], v["chosen"]],
                                 choices=list(v["rcl"]), current=v["chosen"])
            elif rule == "neighbor":
                self.candidates_seen += 1
                # 후보 검토는 5개마다, 실제 개선과 최선해 갱신은 모두 기록한다.
                if self.candidates_seen == 1 or self.candidates_seen % 5 == 0:
                    self.route("neighbor", v["neighbor"], before=list(v["current"].node_ids),
                               previous_waypoints=list(v["current"].waypoints),
                               neighborhood=v.get("idx", 0) + 1, examined=self.candidates_seen,
                               decision_reason="현재 경로를 기준으로 바꿔 본 후보입니다. 이웃 검토가 끝난 뒤 최선 후보의 채택을 결정합니다.")
        elif event == "return":
            if kind == "construct" and arg is not None:
                self.choice_positions.pop(key, None)
                self.iterations += 1
                if arg.route is None:
                    self._record("construction_failed", waypoints=list(v["waypoints"]), construction_call=self.iterations)
                else:
                    self.route("constructed", arg.route, construction_call=self.iterations)
            elif kind == "shake":
                if arg is None:
                    self._record("shake_failed", shake_level=v["shake_level"])
                else:
                    self.route("shake", arg, before=list(v["route"].node_ids), shake_level=v["shake_level"])
            elif kind == "destroy" and arg is not None:
                self._record("destroy", waypoints=list(arg), previous_waypoints=list(v["ids"]), operator=v["method"])
            elif kind == "repair" and arg is not None:
                self._record("repair", waypoints=list(arg.waypoint_ids), operator=v["method"])
            elif kind == "accept" and arg is not None:
                # 내부 ALNS 비용 기준 수락이며 조립 계층의 최종 채택과 다르다.
                parent = frame.f_back.f_locals
                self._record("alns_accept", accepted=bool(arg),
                             waypoints=list(parent["candidate"].waypoint_ids),
                             previous_waypoints=list(parent["current"].waypoint_ids),
                             internal_before={"distance_m": parent["current"].distance_m, "error_m": parent["current"].error_m},
                             internal_after={"distance_m": parent["candidate"].distance_m, "error_m": parent["candidate"].error_m},
                             delta=v["delta"], temperature=v["temperature"],
                             decision_reason=("내부 평가값이 악화되지 않아 수락했습니다." if v["delta"] <= 0 else
                                              "내부 평가값이 악화됐지만 온도에 따른 확률로 수락했습니다." if arg else
                                              "내부 평가값이 악화됐고 온도에 따른 수락 검사에서 기각했습니다."))
            elif kind == "alns_result" and arg is not None:
                details = {}
                if "accepted" in v:
                    details = objective_decision(
                        common.evaluate_route(v["improved"], v["target_m"], v["tolerance"]),
                        common.evaluate_route(v["route"], v["target_m"], v["tolerance"]))
                    reason = details.pop("decision_reason")
                    details.pop("accepted")
                elif "result" not in v:
                    reason = "ALNS 실행 실패로 초기 경로를 유지했습니다."
                elif v.get("new_waypoints") == v["route"].waypoints:
                    reason = "최선 경유지 순서가 기존과 같아 재연결 없이 유지했습니다."
                elif "improved" not in v:
                    reason = "연속 경유지의 최소 간격 조건을 충족하지 못해 기존 경로를 유지했습니다."
                else:
                    reason = "새 경유지를 유효한 도로 경로로 연결하지 못해 기존 경로를 유지했습니다."
                self.route("alns_result", arg, before=list(v["route"].node_ids),
                           previous_waypoints=list(v["route"].waypoints), decision_reason=reason,
                           accepted=v.get("accepted", False), **details)
            # 같은 외부 구축 후보의 입출력이며 VNS 내부 재구축과 구분한다.
            if frame.f_back.f_code is type(self.engine).find_path.__code__ and frame.f_code in {
                fn.__code__ for fn in refine.REFINEMENT_REGISTRY.values()
            } and arg is not None:
                self.route("refinement_done", arg, before=list(v["route"].node_ids),
                           previous_waypoints=list(v["route"].waypoints),
                           changed=arg.node_ids != v["route"].node_ids,
                           decision_reason="같은 초기 후보에 대한 개선 과정이 끝났습니다. 이후 전체 최선 후보와 비교합니다.")
            elif kind == "prune" and arg is not None:
                self._record("prune", [arg], before=list(v["path_nodes"]))
        return self._trace
