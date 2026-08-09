from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Condition
from time import monotonic
from typing import Any


@dataclass(frozen=True)
class EventPage:
    events: list[dict[str, Any]]
    latest_sequence: int
    oldest_sequence: int
    dropped_before: int | None


class EventBuffer:
    def __init__(self, capacity: int = 5000) -> None:
        if capacity < 1:
            raise ValueError("容量必须大于零")
        self._events: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._sequence = 0
        self._condition = Condition()

    @property
    def latest_sequence(self) -> int:
        with self._condition:
            return self._sequence

    def append(self, kind: str, payload: Any) -> dict[str, Any]:
        with self._condition:
            self._sequence += 1
            event = {
                "sequence": self._sequence,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "kind": kind,
                "payload": payload,
            }
            self._events.append(event)
            self._condition.notify_all()
            return event

    def clear(self) -> None:
        with self._condition:
            self._events.clear()

    def get(
        self,
        *,
        after: int = 0,
        limit: int = 200,
        kinds: Iterable[str] | None = None,
        timeout: float = 0,
    ) -> EventPage:
        accepted_kinds = set(kinds or [])
        deadline = monotonic() + max(0, timeout)

        with self._condition:
            while True:
                matching = [
                    event
                    for event in self._events
                    if event["sequence"] > after
                    and (not accepted_kinds or event["kind"] in accepted_kinds)
                ]
                if matching or timeout <= 0:
                    break
                remaining = deadline - monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)

            oldest = self._events[0]["sequence"] if self._events else self._sequence + 1
            dropped_before = oldest if after < oldest - 1 else None
            return EventPage(
                events=matching[: max(1, min(limit, 1000))],
                latest_sequence=self._sequence,
                oldest_sequence=oldest,
                dropped_before=dropped_before,
            )
