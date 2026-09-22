"""실제 artifact·앱 lifespan·LangGraph·StructuredTool을 쓰는 #471 HTTP 검증.

저장소 루트에서 실행: python -m tests.integration.check_circular_preference_artifact
.env의 WALK_GRAPH_SOURCE=artifact와 데이터 버전·파일 경로를 그대로 검증한다.
DB 초기화/인증/저장소와 확인 발화 판정만 대체하며 외부 API를 호출하지 않는다.
pytest의 공통 conftest(전체 LangChain mock)를 거치지 않는 독립 실행 도구다.
"""

import json
import logging
import os
import platform
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

# 설정 import 이전에 외부 tracing과 API 자격 증명을 격리한다.
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["OPENAI_API_KEY"] = "test-unused-api-key"


def _parse_result_event(sse_text: str) -> dict:
    """/api/prewalk/intent 응답(SSE, 2026-09-25 후속)에서 마지막 event: result의 JSON
    data를 파싱한다. prewalk_router.py::_sse()가 만드는 포맷(event: X\\ndata: ...\\n\\n)을
    그대로 가정한다."""
    events: list[tuple[str | None, str]] = []
    for block in sse_text.strip("\n").split("\n\n"):
        if not block:
            continue
        event = None
        data_lines = []
        for line in block.split("\n"):
            if line.startswith("event: "):
                event = line[len("event: "):]
            elif line.startswith("data: "):
                data_lines.append(line[len("data: "):])
        events.append((event, "\n".join(data_lines)))
    result_events = [data for event, data in events if event == "result"]
    assert result_events, f"event: result가 응답에 없습니다: {events!r}"
    return json.loads(result_events[-1])


def main():
    # 서비스 조립과 같은 import 순서를 사용한다.
    import src.main as main_module
    import src.interfaces.dependencies as dependencies
    import networkx as nx
    from fastapi.testclient import TestClient

    from src.config.settings import settings
    from src.infrastructure.cache.repository.chat_state_repository import ChatStateRepository
    from src.infrastructure.external.client.gpt_client import GPTClient
    from src.interfaces.schema.auth_schema import Status
    from src.interfaces.schema.walk_schema import WalkMode, WalkRouteStatus
    from src.repository.layer.route_poi_repository import RoutePoiRepository
    from src.repository.user.route_history_repository import RouteHistoryRepository
    from src.repository.user.user_preference_repository import UserPreferenceRepository
    from src.repository.user.user_repository import UserRepository
    from src.route_engine.scoring.scoring_engine import WeightedEdgeCost
    from src.route_engine.weighted_cost_runtime import get_coverage_report
    from src.schema.prewalk_schema import CircularPreference, FeatureLabel, FeatureTag, Location, State
    from src.service.user.auth_service import AuthService

    assert settings.WALK_GRAPH_SOURCE == "artifact", "WALK_GRAPH_SOURCE=artifact 필요"
    artifact = Path(settings.WALK_GRAPH_ARTIFACT_PATH).resolve()
    manifest = json.loads(artifact.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    assert manifest["data_version"] == settings.WALK_GRAPH_DATA_VERSION
    states = {}
    profile = SimpleNamespace(weights_safety=0.2, weights_comfort=0.4)

    async def load_state(thread_id):
        return states[thread_id].model_copy(deep=True)

    async def save_state(thread_id, state):
        states[thread_id] = state.model_copy(deep=True)

    with ExitStack() as stack:
        stack.enter_context(patch.object(main_module, "init_db"))
        stack.enter_context(patch.object(AuthService, "check_access_token", return_value=(Status.SUCCESS, "test", "test")))
        stack.enter_context(patch.object(UserRepository, "find_by_provider_and_provider_id", return_value=SimpleNamespace(id=1)))
        stack.enter_context(patch.object(UserPreferenceRepository, "get_by_user_id", return_value=profile))
        history = stack.enter_context(patch.object(RouteHistoryRepository, "save", return_value=SimpleNamespace(id=1)))
        stack.enter_context(patch.object(RoutePoiRepository, "find_near_route", return_value=[]))
        stack.enter_context(patch.object(ChatStateRepository, "get_state", side_effect=load_state))
        stack.enter_context(patch.object(ChatStateRepository, "save_state", side_effect=save_state))
        stack.enter_context(patch.object(GPTClient, "get_response", new=AsyncMock(side_effect=AssertionError("외부 LLM 호출 금지"))))

        # 실제 앱 lifespan이 artifact 로드, 점수 준비, ALT 부착, LangGraph 조립을 수행한다.
        client = stack.enter_context(TestClient(main_module.app))
        client.cookies.set("access_token", "test-circular-token")
        logging.getLogger().setLevel(logging.WARNING)
        graph = dependencies.G
        report = get_coverage_report(graph)
        assert report is not None and report.ok, "점수 커버리지 게이트 미통과"
        assert "alt_heuristic" in graph.graph, "ALT 준비 실패"
        print(json.dumps({
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "python": platform.python_version(), "networkx": nx.__version__,
            "artifact": str(artifact), "data_version": manifest["data_version"],
            "sha256": manifest["artifact_sha256"], "source_dirty": manifest["source_dirty"],
            "nodes": graph.number_of_nodes(), "edges": graph.number_of_edges(),
            "coverage": dict(report.ratios), "alt_attached": True,
        }), flush=True)

        service = dependencies.route_service
        original_engine = service.base_engines[WalkMode.CIRCULAR_RANDOM]
        engines = []

        def capture_engine(*args, **kwargs):
            engine = original_engine(*args, **kwargs)
            engines.append(engine)
            return engine

        service.base_engines[WalkMode.CIRCULAR_RANDOM] = capture_engine
        audit = WeightedEdgeCost(0, 0, accident_ratio=settings.WALK_UNSAFE_ACCIDENT_RATIO,
                                 weight_limit=settings.WALK_WEIGHT_LIMIT, medians=report.medians)
        origin = Location(lat=37.5759, lon=126.9768)
        for name, feature in [("distance", None), ("safety", FeatureTag.SAFETY), ("comfort", FeatureTag.COMFORT)]:
            profile.weights_safety, profile.weights_comfort = (0.0, 0.0) if feature is None else (0.2, 0.4)
            labels = {} if feature is None else {
                feature: FeatureLabel(preference_label="high", explicitness_label="explicit_soft"),
            }
            states[name] = State(
                user_id=1, current_location=origin, mode=WalkMode.CIRCULAR_RANDOM,
                user_context=CircularPreference(origin=origin, target_km=3.0),
                awaiting_confirmation=True, feature_labels=labels,
            )
            started = perf_counter()
            response = client.post("/api/prewalk/intent", json={
                # FE는 확인 버튼 클릭 시 confirmation(bool)을 별도로 보낸다(2026-09-24,
                # ConfirmationClassifier 제거 — user_prompt는 "no"의 교정 내용 전용).
                "thread_id": name, "confirmation": True,
                "lat": origin.lat, "lon": origin.lon,
            })
            elapsed = perf_counter() - started
            assert response.status_code == 200, response.status_code
            body = _parse_result_event(response.text)
            assert body["status"] == "success", body["status"]
            routes = body["state"]["route_result"]
            assert routes and all(route["status"] == WalkRouteStatus.SUCCESS for route in routes)
            engine = engines[-1]
            context = engine.cost_context
            route = engine.last_route
            assert route is not None
            if feature is None:
                assert context is None and route.weighted_cost_m == route.distance_m
            else:
                assert context is not None and context.enabled
                safety, comfort = (0.585, 0.4) if feature == FeatureTag.SAFETY else (0.2, 0.645)
                scale = settings.WALK_WEIGHT_LIMIT / (safety + comfort)
                assert abs(context.alpha - safety * scale) < 1e-12
                assert abs(context.beta - comfort * scale) < 1e-12
                assert route.weighted_cost_m > route.distance_m
            for candidate in [route, *engine.last_alternative_routes]:
                if context is not None:
                    total = sum(context.weight(u, v, graph[u][v]) for u, v in zip(candidate.node_ids, candidate.node_ids[1:]))
                    assert abs(candidate.weighted_cost_m - total) < 1e-6
            assert states[name].route_result is not None
            assert len(history.call_args.kwargs["candidate_features"]) == len(routes)
            edges = [graph[u][v] for u, v in zip(route.node_ids, route.node_ids[1:])]
            print(json.dumps({
                "case": name, "status": "success", "candidates": len(routes),
                "alpha": context.alpha if context else 0.0,
                "beta": context.beta if context else 0.0,
                "distance_m": route.distance_m, "weighted_cost_m": route.weighted_cost_m,
                "preference_penalty_ratio": route.weighted_cost_m / route.distance_m - 1,
                "unsafe_mean": sum(e["length"] * audit.unsafe(e) for e in edges) / route.distance_m,
                "discomfort_mean": sum(e["length"] * audit.discomfort(e) for e in edges) / route.distance_m,
                "overlap_ratio": route.repeated_edge_ratio, "seconds": elapsed,
            }), flush=True)


if __name__ == "__main__":
    main()
