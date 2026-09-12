"""실제 엔진의 로컬 상태를 읽는 오프라인 계측. 탐색 구현을 복제하지 않는다."""

from __future__ import annotations

import ast
import hashlib
import inspect
import sys
import textwrap

from src.route_engine.engines.path_utils import PathUtils


def _statement_line(function, predicate):
    source, first = inspect.getsourcelines(function)
    matches = [node for node in ast.walk(ast.parse(textwrap.dedent("".join(source))))
               if predicate(node)]
    if len(matches) != 1:
        raise RuntimeError("엔진 코드 구조가 바뀌었습니다. 시각화 계측 지점을 다시 확인하세요.")
    return first + matches[0].lineno - 1


class SearchTrace:
    """Beam 계열 전용 계측. 현재 스레드에서만 기록하고 종료·예외 시 이전 trace를 복원한다.

    실제 candidates 슬라이스 대입 직후를 매회 읽는다.
    내부 구간 연결 A*는 Beam 화면에서 완성 구간으로만 기록한다.

    최단거리 A*는 더 이상 여기서 기록하지 않는다 — settrace로 NetworkX 내부 프레임을
    읽는 대신 `visualizations/astar_adapter.py`가 실제 실행을 재생해 공통 이벤트를
    만든다. Beam의 settrace는 아직 남아 있다(대체는 PR-B 예정).
    """

    def __init__(self, engine):
        self.engine = engine
        self.events = []
        # A* 기록을 어댑터로 옮긴 뒤로 항상 0이다. 결과 dict의 키를 유지하기 위해 남긴다.
        self.pops = 0
        self.iterations = 0
        self.pending = set()
        self.codes = {}
        self.source_hashes = {}
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
        if values.get("self") not in (self.engine, self.engine.utils):
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
