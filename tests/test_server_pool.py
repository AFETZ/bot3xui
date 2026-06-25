import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.services import server_pool as server_pool_module
from app.bot.services.server_pool import ServerPoolService
from app.db.models import Server


class DummySessionFactory:
    def __call__(self):
        return self

    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return None


def _config():
    return SimpleNamespace(
        xui=SimpleNamespace(
            USERNAME="username",
            PASSWORD="password",
            TOKEN=None,
        )
    )


@pytest.mark.asyncio
async def test_get_connection_restores_missing_server_from_database(monkeypatch):
    server = SimpleNamespace(
        id=3,
        name="Finland",
        host="https://example.test/panel/",
        online=False,
    )
    user = SimpleNamespace(tg_id=123, server_id=3)

    class FakeAsyncApi:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.client = SimpleNamespace(max_retries=3)
            self.inbound = SimpleNamespace(max_retries=3)
            self.database = SimpleNamespace(max_retries=3)
            self.server = SimpleNamespace(max_retries=3)

        async def login(self):
            return None

    update = AsyncMock()
    monkeypatch.setattr(server_pool_module, "AsyncApi", FakeAsyncApi)
    monkeypatch.setattr(Server, "get_by_id", AsyncMock(return_value=server))
    monkeypatch.setattr(Server, "update", update)

    service = ServerPoolService(config=_config(), session=DummySessionFactory())

    connection = await service.get_connection(user)

    assert connection is not None
    assert connection.server is server
    assert connection.api.kwargs["host"] == server.host
    assert connection.api.kwargs["logger"].level == logging.WARNING
    assert connection.api.client.max_retries == 1
    assert connection.api.inbound.max_retries == 1
    assert connection.api.database.max_retries == 1
    assert connection.api.server.max_retries == 1
    assert service._servers[3] is connection
    assert server.online is True
    update.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_connection_keeps_missing_server_unavailable_when_restore_fails(monkeypatch):
    server = SimpleNamespace(
        id=3,
        name="Finland",
        host="https://example.test/panel/",
        online=True,
    )
    user = SimpleNamespace(tg_id=123, server_id=3)

    class FailingAsyncApi:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def login(self):
            raise TimeoutError

    update = AsyncMock()
    monkeypatch.setattr(server_pool_module, "AsyncApi", FailingAsyncApi)
    monkeypatch.setattr(Server, "get_by_id", AsyncMock(return_value=server))
    monkeypatch.setattr(Server, "update", update)

    service = ServerPoolService(config=_config(), session=DummySessionFactory())

    connection = await service.get_connection(user)

    assert connection is None
    assert service._servers == {}
    assert server.online is False
    update.assert_awaited_once()
