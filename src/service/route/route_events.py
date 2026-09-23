"""Route processing events shared by the route service and chatbot stream."""

from __future__ import annotations

import contextvars
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterator

logger = logging.getLogger(__name__)

EVENT_TYPES = (
    "route_request_started",
    "shortest_path_completed",
    "candidates_generated",
    "representative_route_selected",
    "route_response_completed",
)


@dataclass(frozen=True)
class RouteEvent:
    request_id: str
    event_type: str
    occurred_at: str
    result: dict[str, Any]
    user_id: str | int | None = None
    session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RouteEventCollector:
    def __init__(self, request_id: str, user_id=None, session_id: str | None = None):
        self.request_id = request_id
        self.user_id = user_id
        self.session_id = session_id
        self.events: list[RouteEvent] = []

    def emit(self, event_type: str, result: dict[str, Any] | None = None) -> None:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unknown route event type: {event_type}")
        self.events.append(RouteEvent(
            request_id=self.request_id,
            event_type=event_type,
            occurred_at=datetime.now(timezone.utc).isoformat(),
            result=result or {}, user_id=self.user_id, session_id=self.session_id,
        ))


_current_collector: contextvars.ContextVar[RouteEventCollector | None] = contextvars.ContextVar(
    "route_event_collector", default=None
)


def event_scope(collector: RouteEventCollector):
    return _current_collector.set(collector)


def reset_event_scope(token) -> None:
    _current_collector.reset(token)


def emit_route_event(event_type: str, **result: Any) -> None:
    """Best-effort hook: observability must never change route behaviour."""
    collector = _current_collector.get()
    if collector is None:
        return
    try:
        collector.emit(event_type, result)
    except Exception:
        logger.exception("route event emission failed: event_type=%s", event_type)


def iter_events(collector: RouteEventCollector) -> Iterator[dict[str, Any]]:
    for event in collector.events:
        yield event.to_dict()
