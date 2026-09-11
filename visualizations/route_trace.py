"""실제 엔진의 로컬 상태를 읽는 오프라인 계측. 탐색 구현을 복제하지 않는다."""

from __future__ import annotations

import ast
import hashlib
import inspect
import sys
import textwrap

import networkx as nx

from src.route_engine.engines.path_utils import PathUtils


def _statement_line(function, predicate):
    source, first = inspect.getsourcelines(function)
    matches = [node for node in ast.walk(ast.parse(textwrap.dedent("".join(source))))
               if predicate(node)]
    if len(matches) != 1:
        raise RuntimeError("엔진 코드 구조가 바뀌었습니다. 시각화 계측 지점을 다시 확인하세요.")
    return first + matches[0].lineno - 1


class SearchTrace:
    """현재 스레드에서만 기록하고 종료·예외 시 이전 trace를 복원한다.

    Beam은 실제 candidates 슬라이스 대입 직후, A*는 우선순위 큐에서
    항목을 꺼낸 직후를 매회 읽는다.
    내부 구간 연결 A*는 Beam 화면에서 완성 구간으로만 기록한다.
    """

    def __init__(self, engine, shortest=False):
        self.engine = engine
        self.events = []
        self.pops = 0
        self.iterations = 0
        self.pending = set()
        self.codes = {}
        self.source_hashes = {}
        if shortest:
            function = inspect.unwrap(nx.astar_path)
            line = _statement_line(function, lambda n: isinstance(n, ast.If)
                                   and ast.unparse(n.test) == "curnode == target")
            self._register(function, "astar", line)
        else:
            function = type(engine)._find_start_to_waypoint
            line = _statement_line(function, lambda n: isinstance(n, ast.Assign)
                                   and any(isinstance(t, ast.Name) and t.id == "beams" for t in n.targets)
                                   and isinstance(n.value, ast.Subscript))
            self._register(function, "beam", line)
            self._register(type(engine).find_path, "selection")
            self._register(PathUtils.connect_to, "connect")
            self._register(PathUtils.prune_dead_ends, "prune")

    def _register(self, function, kind, line=None):
        self.codes[function.__code__] = (kind, line)
        self.source_hashes[function.__qualname__] = hashlib.sha256(
            inspect.getsource(function).encode()).hexdigest()

    def _record(self, phase, paths=(), **values):
        self.events.append({"phase": phase, "paths": [list(p) for p in paths], **values})

    def _trace(self, frame, event, arg):
        spec = self.codes.get(frame.f_code)
        if spec is None:
            return None
        kind, line = spec
        values = frame.f_locals
        if kind != "astar" and values.get("self") not in (self.engine, self.engine.utils):
            return None
        if kind == "astar" and values.get("G") is not self.engine.G:
            return None
        if kind == "beam":
            key = id(frame)
            if key in self.pending and event in ("line", "return"):
                self.pending.remove(key)
                self.iterations += 1
                candidates, beams = values["candidates"], values["beams"]
                common = {"iteration": self.iterations, "generated": len(candidates),
                          "kept": len(beams), "finished": len(values["finished"])}
                self._record("expand", [b[1] for b in candidates], **common)
                self._record("keep", [b[1] for b in beams], **common)
            if event == "line" and frame.f_lineno == line:
                self.pending.add(key)
        elif kind == "astar" and event == "line" and frame.f_lineno == line:
            self.pops += 1
            node = values["curnode"]
            chain, parent = [node], values["parent"]
            while parent is not None:
                chain.append(parent)
                parent = values["explored"][parent]
            chain.reverse()
            self._record("astar", [chain], current=node, popped=self.pops,
                         tree=[[parent, child] for child, parent in values["explored"].items() if parent is not None],
                         explored=list(values["explored"]),
                         frontier=sorted({item[2] for item in values["queue"]}),
                         distance_m=values["dist"])
        elif event == "return" and arg is not None:
            if kind == "selection":
                self._record("selection", arg)
            elif kind == "connect":
                self._record("connect", [arg])
            elif kind == "prune":
                self._record("prune", [arg], before=list(values["path_nodes"]))
        return self._trace

    def __enter__(self):
        self.previous = sys.gettrace()
        if self.previous is not None:
            raise RuntimeError("디버거·커버리지 trace를 끄고 시각화를 별도로 실행하세요.")
        sys.settrace(self._trace)
        return self

    def __exit__(self, *_):
        sys.settrace(self.previous)
