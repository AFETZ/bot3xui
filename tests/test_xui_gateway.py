from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.services.xui_gateway import XuiCircuitOpenError, XuiGateway


@pytest.mark.asyncio
async def test_xui_gateway_opens_circuit_after_repeated_failures():
    connection = SimpleNamespace(
        server=SimpleNamespace(id=1, name="Finland"),
        api=SimpleNamespace(
            client=SimpleNamespace(
                get_by_email=AsyncMock(side_effect=TimeoutError("panel timeout"))
            )
        ),
    )
    gateway = XuiGateway(
        call_timeout_seconds=0.1,
        failure_threshold=2,
        recovery_timeout_seconds=60,
    )

    with pytest.raises(TimeoutError):
        await gateway.get_client_by_email(connection, "123")

    with pytest.raises(TimeoutError):
        await gateway.get_client_by_email(connection, "123")

    with pytest.raises(XuiCircuitOpenError):
        await gateway.get_client_by_email(connection, "123")

    assert connection.api.client.get_by_email.await_count == 2
    health = gateway.get_health_snapshot()
    assert health[0]["circuit_open"] is True
    assert health[0]["failure_count"] == 2


@pytest.mark.asyncio
async def test_xui_gateway_does_not_open_circuit_for_missing_client():
    connection = SimpleNamespace(
        server=SimpleNamespace(id=2, name="Kazakhstan"),
        api=SimpleNamespace(
            client=SimpleNamespace(
                get_by_email=AsyncMock(
                    side_effect=RuntimeError("Inbound Not Found For Email: 123")
                )
            )
        ),
    )
    gateway = XuiGateway(
        call_timeout_seconds=0.1,
        failure_threshold=1,
        recovery_timeout_seconds=60,
    )

    with pytest.raises(RuntimeError):
        await gateway.get_client_by_email(connection, "123")

    health = gateway.get_health_snapshot()
    assert health[0]["circuit_open"] is False
    assert health[0]["failure_count"] == 0
