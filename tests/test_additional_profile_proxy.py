from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import ClientError, web
from aiohttp.test_utils import make_mocked_request

from app.web.additional_profile import AdditionalProfileProxy


class FakeUpstreamResponse:
    def __init__(self, status=200, text="profile-data"):
        self.status = status
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self, encoding="utf-8"):
        return self._text


class FakeClientSession:
    def __init__(self, response=None, error=None, **kwargs):
        self.response = response
        self.error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def get(self, url):
        if self.error:
            raise self.error
        return self.response


def make_request(vpn_id="vpn-1"):
    return make_mocked_request("GET", f"/wl/{vpn_id}", match_info={"vpn_id": vpn_id})


@pytest.mark.asyncio
async def test_proxy_returns_403_for_unknown_user():
    service = SimpleNamespace(
        get_subscription_status_by_vpn_id=AsyncMock(return_value=(None, None))
    )
    proxy = AdditionalProfileProxy(subscription_service=service)

    with pytest.raises(web.HTTPForbidden):
        await proxy.handle(make_request())


@pytest.mark.asyncio
async def test_proxy_returns_503_when_status_check_failed():
    user = SimpleNamespace(tg_id=1)
    status = SimpleNamespace(status_check_ok=False, is_active=True, has_additional_profile=True)
    service = SimpleNamespace(
        get_subscription_status_by_vpn_id=AsyncMock(return_value=(user, status))
    )
    proxy = AdditionalProfileProxy(subscription_service=service)

    with pytest.raises(web.HTTPServiceUnavailable):
        await proxy.handle(make_request())


@pytest.mark.asyncio
async def test_proxy_returns_403_when_user_has_no_entitlement():
    user = SimpleNamespace(tg_id=1)
    status = SimpleNamespace(status_check_ok=True, is_active=True, has_additional_profile=False)
    service = SimpleNamespace(
        get_subscription_status_by_vpn_id=AsyncMock(return_value=(user, status))
    )
    proxy = AdditionalProfileProxy(subscription_service=service)

    with pytest.raises(web.HTTPForbidden):
        await proxy.handle(make_request())


@pytest.mark.asyncio
async def test_proxy_returns_502_on_upstream_errors(monkeypatch):
    user = SimpleNamespace(tg_id=1)
    status = SimpleNamespace(status_check_ok=True, is_active=True, has_additional_profile=True)
    service = SimpleNamespace(
        get_subscription_status_by_vpn_id=AsyncMock(return_value=(user, status))
    )
    proxy = AdditionalProfileProxy(subscription_service=service)

    monkeypatch.setattr(
        "app.web.additional_profile.aiohttp.ClientSession",
        lambda **kwargs: FakeClientSession(error=ClientError("boom")),
    )

    with pytest.raises(web.HTTPBadGateway):
        await proxy.handle(make_request())


@pytest.mark.asyncio
async def test_proxy_returns_upstream_content(monkeypatch):
    user = SimpleNamespace(tg_id=1)
    status = SimpleNamespace(status_check_ok=True, is_active=True, has_additional_profile=True)
    service = SimpleNamespace(
        get_subscription_status_by_vpn_id=AsyncMock(return_value=(user, status))
    )
    proxy = AdditionalProfileProxy(subscription_service=service)

    monkeypatch.setattr(
        "app.web.additional_profile.aiohttp.ClientSession",
        lambda **kwargs: FakeClientSession(response=FakeUpstreamResponse(text="live-profile")),
    )

    response = await proxy.handle(make_request("vpn-allowed"))

    assert response.status == 200
    assert response.text == "live-profile"
    assert response.content_type == "text/plain"
    assert response.charset == "utf-8"
    assert response.headers["Cache-Control"] == "no-store, no-cache, must-revalidate"
