from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, TypeVar

from py3xui import Client, Inbound

from app.bot.services.runtime_metrics import runtime_metrics

if TYPE_CHECKING:
    from .server_pool import Connection

logger = logging.getLogger(__name__)

T = TypeVar("T")


class XuiCircuitOpenError(RuntimeError):
    pass


@dataclass
class CircuitBreakerState:
    server_id: int
    server_name: str
    failure_count: int = 0
    opened_at: float | None = None
    last_failure: str | None = None
    last_failure_at: datetime | None = None
    last_success_at: datetime | None = None

    @property
    def is_open(self) -> bool:
        return self.opened_at is not None

    def can_call(self, recovery_timeout_seconds: float) -> bool:
        if self.opened_at is None:
            return True
        return time.monotonic() - self.opened_at >= recovery_timeout_seconds

    def record_success(self) -> None:
        self.failure_count = 0
        self.opened_at = None
        self.last_failure = None
        self.last_success_at = datetime.now(timezone.utc)

    def record_failure(self, exception: Exception, failure_threshold: int) -> None:
        self.failure_count += 1
        self.last_failure = str(exception)
        self.last_failure_at = datetime.now(timezone.utc)
        if self.failure_count >= failure_threshold:
            self.opened_at = time.monotonic()


class XuiGateway:
    def __init__(
        self,
        *,
        call_timeout_seconds: float = 12,
        failure_threshold: int = 3,
        recovery_timeout_seconds: float = 60,
    ) -> None:
        self.call_timeout_seconds = call_timeout_seconds
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self._states: dict[int, CircuitBreakerState] = {}

    @staticmethod
    def _is_client_not_found_error(exception: Exception) -> bool:
        error_text = str(exception).lower()
        return (
            "inbound not found for email" in error_text
            or "not found for email" in error_text
            or "error getting traffics" in error_text
        )

    def _state_for(self, connection: "Connection") -> CircuitBreakerState:
        server_id = connection.server.id
        state = self._states.get(server_id)
        if state is None:
            state = CircuitBreakerState(
                server_id=server_id,
                server_name=connection.server.name,
            )
            self._states[server_id] = state
        else:
            state.server_name = connection.server.name
        return state

    async def _call(
        self,
        connection: "Connection",
        operation: str,
        call: Callable[[], Awaitable[T]],
    ) -> T:
        state = self._state_for(connection)
        if not state.can_call(self.recovery_timeout_seconds):
            runtime_metrics.increment("xui.circuit_rejected")
            runtime_metrics.record_xui_server(
                state.server_id,
                name=state.server_name,
                circuit_open=True,
                failure_count=state.failure_count,
                last_failure=state.last_failure,
            )
            raise XuiCircuitOpenError(
                f"3x-ui circuit is open for server {state.server_name}."
            )

        started_at = time.monotonic()
        try:
            result = await asyncio.wait_for(call(), timeout=self.call_timeout_seconds)
        except Exception as exception:
            if operation == "client.get_by_email" and self._is_client_not_found_error(
                exception
            ):
                state.record_success()
                runtime_metrics.increment("xui.client_not_found")
                runtime_metrics.record_xui_server(
                    state.server_id,
                    name=state.server_name,
                    circuit_open=False,
                    failure_count=0,
                    operation=operation,
                )
                raise

            state.record_failure(exception, self.failure_threshold)
            runtime_metrics.increment("xui.calls_failed")
            runtime_metrics.record_xui_server(
                state.server_id,
                name=state.server_name,
                circuit_open=state.is_open,
                failure_count=state.failure_count,
                last_failure=state.last_failure,
                operation=operation,
            )
            logger.warning(
                "3x-ui %s failed on server %s: %s",
                operation,
                state.server_name,
                exception,
            )
            raise

        state.record_success()
        runtime_metrics.increment("xui.calls_ok")
        runtime_metrics.set_gauge(
            f"xui.{state.server_id}.{operation}.duration_seconds",
            round(time.monotonic() - started_at, 3),
        )
        runtime_metrics.record_xui_server(
            state.server_id,
            name=state.server_name,
            circuit_open=False,
            failure_count=0,
            operation=operation,
        )
        return result

    async def get_client_by_email(self, connection: "Connection", email: str) -> Client | None:
        return await self._call(
            connection,
            "client.get_by_email",
            lambda: connection.api.client.get_by_email(email),
        )

    async def get_inbound_list(self, connection: "Connection") -> list[Inbound] | None:
        return await self._call(
            connection,
            "inbound.get_list",
            connection.api.inbound.get_list,
        )

    async def add_client(
        self,
        connection: "Connection",
        *,
        inbound_id: int,
        clients: list[Client],
    ) -> Any:
        return await self._call(
            connection,
            "client.add",
            lambda: connection.api.client.add(inbound_id=inbound_id, clients=clients),
        )

    async def update_client(
        self,
        connection: "Connection",
        *,
        client_uuid: str,
        client: Client,
    ) -> Any:
        return await self._call(
            connection,
            "client.update",
            lambda: connection.api.client.update(client_uuid=client_uuid, client=client),
        )

    def get_health_snapshot(self) -> list[dict[str, Any]]:
        return [
            {
                "server_id": state.server_id,
                "server_name": state.server_name,
                "circuit_open": state.is_open,
                "failure_count": state.failure_count,
                "last_failure": state.last_failure,
                "last_failure_at": state.last_failure_at,
                "last_success_at": state.last_success_at,
            }
            for state in sorted(self._states.values(), key=lambda item: item.server_name)
        ]
