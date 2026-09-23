import json

from src.service.route.route_events import (
    EVENT_TYPES,
    RouteEventCollector,
    emit_route_event,
    event_scope,
    reset_event_scope,
)


def test_route_events_keep_common_payload_and_emission_order():
    collector = RouteEventCollector(request_id="req-1", session_id="session-1")
    token = event_scope(collector)
    try:
        for event_type in EVENT_TYPES:
            emit_route_event(event_type, status="success")
    finally:
        reset_event_scope(token)

    payloads = [event.to_dict() for event in collector.events]
    assert [payload["event_type"] for payload in payloads] == list(EVENT_TYPES)
    assert all(payload["request_id"] == "req-1" for payload in payloads)
    assert all(payload["session_id"] == "session-1" for payload in payloads)
    assert all(payload["occurred_at"] for payload in payloads)
    assert all(payload["result"] == {"status": "success"} for payload in payloads)
    json.dumps(payloads)


def test_route_event_without_scope_is_ignored():
    emit_route_event("route_request_started", mode="oneway_shortest")


def test_route_event_emission_failure_does_not_escape(monkeypatch):
    collector = RouteEventCollector(request_id="req-1")
    token = event_scope(collector)
    try:
        def fail(*args, **kwargs):
            raise RuntimeError("collector unavailable")

        monkeypatch.setattr(collector, "emit", fail)
        emit_route_event("route_response_completed", status="success")
    finally:
        reset_event_scope(token)

    assert collector.events == []
