from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import ClientError, web
from aiohttp.test_utils import make_mocked_request

from app.web.primary_profile import PrimaryProfileProxy


class FakeUpstreamResponse:
    def __init__(self, status=200, body=b"profile-data", headers=None):
        self.status = status
        self._body = body
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def read(self):
        return self._body


class FakeClientSession:
    def __init__(self, response=None, error=None, **kwargs):
        self.response = response
        self.error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def get(self, url, **kwargs):
        if self.error:
            raise self.error
        return self.response


def make_request(vpn_id="vpn-1", headers=None):
    return make_mocked_request(
        "GET",
        f"/sub/{vpn_id}",
        match_info={"vpn_id": vpn_id},
        headers=headers or {"User-Agent": "Happ"},
    )


@pytest.mark.asyncio
async def test_proxy_returns_403_for_unknown_user():
    service = SimpleNamespace(
        get_subscription_status_by_vpn_id=AsyncMock(return_value=(None, None))
    )
    proxy = PrimaryProfileProxy(subscription_service=service)

    with pytest.raises(web.HTTPForbidden):
        await proxy.handle(make_request())


@pytest.mark.asyncio
async def test_proxy_returns_503_when_status_check_failed():
    user = SimpleNamespace(tg_id=1)
    status = SimpleNamespace(status_check_ok=False, is_active=True)
    service = SimpleNamespace(
        get_subscription_status_by_vpn_id=AsyncMock(return_value=(user, status))
    )
    proxy = PrimaryProfileProxy(subscription_service=service)

    with pytest.raises(web.HTTPServiceUnavailable):
        await proxy.handle(make_request())


@pytest.mark.asyncio
async def test_proxy_returns_403_when_subscription_inactive():
    user = SimpleNamespace(tg_id=1)
    status = SimpleNamespace(status_check_ok=True, is_active=False)
    service = SimpleNamespace(
        get_subscription_status_by_vpn_id=AsyncMock(return_value=(user, status))
    )
    proxy = PrimaryProfileProxy(subscription_service=service)

    with pytest.raises(web.HTTPForbidden):
        await proxy.handle(make_request())


@pytest.mark.asyncio
async def test_proxy_returns_502_on_missing_upstream_url():
    user = SimpleNamespace(tg_id=1)
    status = SimpleNamespace(status_check_ok=True, is_active=True)
    service = SimpleNamespace(
        get_subscription_status_by_vpn_id=AsyncMock(return_value=(user, status)),
        get_upstream_profile_url=AsyncMock(return_value=None),
    )
    proxy = PrimaryProfileProxy(subscription_service=service)

    with pytest.raises(web.HTTPBadGateway):
        await proxy.handle(make_request())


@pytest.mark.asyncio
async def test_proxy_returns_502_on_upstream_errors(monkeypatch):
    user = SimpleNamespace(tg_id=1)
    status = SimpleNamespace(status_check_ok=True, is_active=True)
    service = SimpleNamespace(
        get_subscription_status_by_vpn_id=AsyncMock(return_value=(user, status)),
        get_upstream_profile_url=AsyncMock(return_value="https://xui.example/sub/vpn-1"),
    )
    proxy = PrimaryProfileProxy(subscription_service=service)

    monkeypatch.setattr(
        "app.web.primary_profile.aiohttp.ClientSession",
        lambda **kwargs: FakeClientSession(error=ClientError("boom")),
    )

    with pytest.raises(web.HTTPBadGateway):
        await proxy.handle(make_request())


@pytest.mark.asyncio
async def test_proxy_decodes_base64_profile_and_drops_empty_base64_title(monkeypatch):
    user = SimpleNamespace(tg_id=1)
    status = SimpleNamespace(status_check_ok=True, is_active=True)
    service = SimpleNamespace(
        get_subscription_status_by_vpn_id=AsyncMock(return_value=(user, status)),
        get_upstream_profile_url=AsyncMock(return_value="https://xui.example/sub/vpn-1"),
    )
    proxy = PrimaryProfileProxy(subscription_service=service)

    upstream_body = b"dmxlc3M6Ly9hYmM=\n"
    upstream_headers = {
        "Content-Type": "text/plain; charset=utf-8",
        "Profile-Title": "base64:",
        "Profile-Update-Interval": "12",
        "Subscription-Userinfo": "upload=10; download=20; total=0; expire=1780036773",
    }

    monkeypatch.setattr(
        "app.web.primary_profile.aiohttp.ClientSession",
        lambda **kwargs: FakeClientSession(
            response=FakeUpstreamResponse(body=upstream_body, headers=upstream_headers)
        ),
    )

    response = await proxy.handle(make_request("vpn-allowed"))

    assert response.status == 200
    assert response.body == b"vless://abc"
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert "profile-title" not in response.headers
    assert response.headers["profile-update-interval"] == "12"
    assert (
        response.headers["subscription-userinfo"]
        == "upload=10; download=20; total=0; expire=1780036773"
    )


@pytest.mark.asyncio
async def test_proxy_keeps_plain_profile_body_unchanged(monkeypatch):
    user = SimpleNamespace(tg_id=1)
    status = SimpleNamespace(status_check_ok=True, is_active=True)
    service = SimpleNamespace(
        get_subscription_status_by_vpn_id=AsyncMock(return_value=(user, status)),
        get_upstream_profile_url=AsyncMock(return_value="https://xui.example/sub/vpn-1"),
    )
    proxy = PrimaryProfileProxy(subscription_service=service)

    upstream_body = b"vless://abc\n"
    upstream_headers = {
        "Content-Type": "text/plain; charset=utf-8",
        "Profile-Title": "Name VPN",
    }

    monkeypatch.setattr(
        "app.web.primary_profile.aiohttp.ClientSession",
        lambda **kwargs: FakeClientSession(
            response=FakeUpstreamResponse(body=upstream_body, headers=upstream_headers)
        ),
    )

    response = await proxy.handle(make_request("vpn-allowed"))

    assert response.body == upstream_body
    assert response.headers["profile-title"] == "Name VPN"


@pytest.mark.asyncio
async def test_proxy_falls_back_to_text_plain_when_upstream_missing_content_type(monkeypatch):
    user = SimpleNamespace(tg_id=1)
    status = SimpleNamespace(status_check_ok=True, is_active=True)
    service = SimpleNamespace(
        get_subscription_status_by_vpn_id=AsyncMock(return_value=(user, status)),
        get_upstream_profile_url=AsyncMock(return_value="https://xui.example/sub/vpn-1"),
    )
    proxy = PrimaryProfileProxy(subscription_service=service)

    monkeypatch.setattr(
        "app.web.primary_profile.aiohttp.ClientSession",
        lambda **kwargs: FakeClientSession(
            response=FakeUpstreamResponse(body=b"data", headers={})
        ),
    )

    response = await proxy.handle(make_request("vpn-allowed"))

    assert response.headers["content-type"] == "text/plain; charset=utf-8"
