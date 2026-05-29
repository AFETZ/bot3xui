from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.services.vpn import VPNService
from app.db.models import User


class DummySessionFactory:
    def __call__(self):
        return self

    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return None


def _service(subscription_scheme="http", server_pool_service=None):
    config = SimpleNamespace(
        xui=SimpleNamespace(
            SUBSCRIPTION_PORT=2096,
            SUBSCRIPTION_PATH="/sub/",
            SUBSCRIPTION_SCHEME=subscription_scheme,
        )
    )
    return VPNService(
        config=config,
        session=DummySessionFactory(),
        server_pool_service=server_pool_service or SimpleNamespace(),
    )


@pytest.mark.asyncio
async def test_get_upstream_key_uses_http_server_scheme(monkeypatch):
    user = SimpleNamespace(
        tg_id=1,
        server_id=1,
        vpn_id="vpn-1",
        server=SimpleNamespace(host="http://46.8.43.253:5865/panel/"),
    )
    monkeypatch.setattr(User, "get", AsyncMock(return_value=user))

    assert await _service(subscription_scheme="http").get_upstream_key(user) == (
        "http://46.8.43.253:2096/sub/vpn-1"
    )


@pytest.mark.asyncio
async def test_get_upstream_key_keeps_https_server_scheme(monkeypatch):
    user = SimpleNamespace(
        tg_id=1,
        server_id=1,
        vpn_id="vpn-1",
        server=SimpleNamespace(host="https://www.superbebra.uk:5865/panel/"),
    )
    monkeypatch.setattr(User, "get", AsyncMock(return_value=user))

    assert await _service(subscription_scheme="http").get_upstream_key(user) == (
        "https://www.superbebra.uk:2096/sub/vpn-1"
    )


@pytest.mark.asyncio
async def test_switch_server_updates_user_when_client_exists(monkeypatch):
    server = SimpleNamespace(id=2, name="Finland", online=True)
    connection = SimpleNamespace(
        server=server,
        api=SimpleNamespace(client=SimpleNamespace(get_by_email=AsyncMock(return_value=object()))),
    )
    server_pool = SimpleNamespace(
        get_connection_by_server_id=AsyncMock(return_value=connection)
    )
    monkeypatch.setattr(User, "update", AsyncMock())
    user = SimpleNamespace(tg_id=123, server_id=1, server=None)

    result = await _service(server_pool_service=server_pool).switch_server(user, 2)

    assert result.success is True
    assert result.reason == "switched"
    assert result.server is server
    assert user.server_id == 2
    User.update.assert_awaited_once()


@pytest.mark.asyncio
async def test_switch_server_rejects_server_without_client(monkeypatch):
    server = SimpleNamespace(id=2, name="Finland", online=True)
    connection = SimpleNamespace(
        server=server,
        api=SimpleNamespace(client=SimpleNamespace(get_by_email=AsyncMock(return_value=None))),
    )
    server_pool = SimpleNamespace(
        get_connection_by_server_id=AsyncMock(return_value=connection)
    )
    monkeypatch.setattr(User, "update", AsyncMock())
    user = SimpleNamespace(tg_id=123, server_id=1, server=None)

    result = await _service(server_pool_service=server_pool).switch_server(user, 2)

    assert result.success is False
    assert result.reason == "client_missing"
    User.update.assert_not_awaited()
