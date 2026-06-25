from __future__ import annotations

import os
import resource
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def open_fd_count() -> int | None:
    fd_path = "/proc/self/fd"
    if not os.path.exists(fd_path):
        return None

    try:
        return len(os.listdir(fd_path))
    except OSError:
        return None


def fd_limits() -> tuple[int | str, int | str]:
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    soft_value: int | str = "unlimited" if soft == resource.RLIM_INFINITY else soft
    hard_value: int | str = "unlimited" if hard == resource.RLIM_INFINITY else hard
    return soft_value, hard_value


@dataclass
class RuntimeMetrics:
    counters: dict[str, int] = field(default_factory=dict)
    gauges: dict[str, int | float | str | None] = field(default_factory=dict)
    events: dict[str, dict[str, Any]] = field(default_factory=dict)
    xui_servers: dict[int, dict[str, Any]] = field(default_factory=dict)
    started_at: datetime = field(default_factory=utc_now)

    def increment(self, key: str, amount: int = 1) -> None:
        self.counters[key] = self.counters.get(key, 0) + amount

    def set_gauge(self, key: str, value: int | float | str | None) -> None:
        self.gauges[key] = value

    def record_event(self, key: str, **values: Any) -> None:
        self.events[key] = {
            "at": utc_now(),
            **values,
        }

    def record_duration(self, key: str, started_at: float) -> None:
        self.set_gauge(key, round(time.monotonic() - started_at, 3))

    def record_xui_server(self, server_id: int, **values: Any) -> None:
        current = self.xui_servers.get(server_id, {})
        self.xui_servers[server_id] = {
            **current,
            "updated_at": utc_now(),
            **values,
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "counters": dict(self.counters),
            "gauges": dict(self.gauges),
            "events": {key: dict(value) for key, value in self.events.items()},
            "xui_servers": {
                server_id: dict(value)
                for server_id, value in self.xui_servers.items()
            },
        }


runtime_metrics = RuntimeMetrics()
