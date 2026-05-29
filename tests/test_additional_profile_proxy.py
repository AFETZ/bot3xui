from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import ClientError, web
from aiohttp.test_utils import make_mocked_request

from app.web.additional_profile import (
    ADDITIONAL_PROFILE_MIRROR_URLS,
    AdditionalProfileProxy,
)


PROFILE_TEXT = "vless://live-profile\n# profile comment"


class FakeUpstreamResponse:
    def __init__(self, status=200, text=PROFILE_TEXT):
        self.status = status
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self, encoding="utf-8"):
        return self._text


class FakeClientSession:
    def __init__(self, responses=None, error=None, calls=None, **kwargs):
        self.responses = list(responses or [])
        self.error = error
        self.calls = calls if calls is not None else []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        if not self.responses:
            raise ClientError("unexpected mirror request")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def make_request(vpn_id="vpn-1"):
    return make_mocked_request("GET", f"/wl/{vpn_id}", match_info={"vpn_id": vpn_id})


def make_active_service():
    user = SimpleNamespace(tg_id=1)
    status = SimpleNamespace(status_check_ok=True, is_active=True, has_additional_profile=True)
    return SimpleNamespace(
        get_subscription_status_by_vpn_id=AsyncMock(return_value=(user, status))
    )


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
    service = make_active_service()
    proxy = AdditionalProfileProxy(subscription_service=service)

    monkeypatch.setattr(
        "app.web.additional_profile.aiohttp.ClientSession",
        lambda **kwargs: FakeClientSession(error=ClientError("boom")),
    )

    with pytest.raises(web.HTTPBadGateway):
        await proxy.handle(make_request())


@pytest.mark.asyncio
async def test_proxy_falls_back_from_first_mirror_to_second(monkeypatch):
    calls = []
    service = make_active_service()
    proxy = AdditionalProfileProxy(subscription_service=service)

    monkeypatch.setattr(
        "app.web.additional_profile.aiohttp.ClientSession",
        lambda **kwargs: FakeClientSession(
            calls=calls,
            responses=[
                FakeUpstreamResponse(status=503),
                FakeUpstreamResponse(text=PROFILE_TEXT),
            ],
        ),
    )

    response = await proxy.handle(make_request("vpn-allowed"))

    assert response.status == 200
    assert response.text == PROFILE_TEXT
    assert response.content_type == "text/plain"
    assert response.charset == "utf-8"
    assert response.headers["Cache-Control"] == "no-store, no-cache, must-revalidate"
    assert response.headers["profile-title"] == "AFZVPN Universal WL"
    assert response.headers["profile-update-interval"] == "1"
    assert response.headers["subscription-auto-update-enable"] == "1"
    assert response.headers["subscription-ping-onopen-enabled"] == "1"
    assert response.headers["ping-type"] == "proxy-head"
    assert response.headers["check-url-via-proxy"] == "https://cp.cloudflare.com/generate_204"
    assert "subscription-autoconnect" not in response.headers
    assert "subscription-autoconnect-type" not in response.headers
    assert response.headers["X-Profile-Source"] == ADDITIONAL_PROFILE_MIRROR_URLS[1]
    assert response.headers["X-Profile-Stale"] == "0"
    assert [url for url, _ in calls] == list(ADDITIONAL_PROFILE_MIRROR_URLS[:2])
    assert calls[0][1]["timeout"].total == 5


def test_proxy_mirror_order_keeps_experimental_sources_last():
    assert ADDITIONAL_PROFILE_MIRROR_URLS[:3] == (
        "https://raw.githubusercontent.com/zieng2/wl/main/vless_universal.txt",
        "https://codeberg.org/zieng2/wl/raw/branch/main/vless_universal.txt",
        "https://gitlab.com/zieng2/wl/raw/main/vless_universal.txt",
    )
    assert ADDITIONAL_PROFILE_MIRROR_URLS[3:] == (
        "https://hub.mos.ru/zieng2/wl/raw/main/list_universal.txt",
        "https://gitverse.ru/api/repos/zieng2/wl/raw/branch/master/list_universal.txt",
    )


@pytest.mark.asyncio
async def test_proxy_returns_cached_profile_when_all_mirrors_fail_after_success(monkeypatch):
    service = make_active_service()
    proxy = AdditionalProfileProxy(subscription_service=service)

    monkeypatch.setattr(
        "app.web.additional_profile.aiohttp.ClientSession",
        lambda **kwargs: FakeClientSession(
            responses=[FakeUpstreamResponse(text=PROFILE_TEXT)],
        ),
    )

    first_response = await proxy.handle(make_request("vpn-allowed"))
    assert first_response.headers["X-Profile-Stale"] == "0"

    monkeypatch.setattr(
        "app.web.additional_profile.aiohttp.ClientSession",
        lambda **kwargs: FakeClientSession(error=ClientError("boom")),
    )

    stale_response = await proxy.handle(make_request("vpn-allowed"))

    assert stale_response.status == 200
    assert stale_response.text == PROFILE_TEXT
    assert stale_response.headers["X-Profile-Source"] == ADDITIONAL_PROFILE_MIRROR_URLS[0]
    assert stale_response.headers["X-Profile-Stale"] == "1"


@pytest.mark.asyncio
async def test_proxy_rejects_empty_and_html_like_profile_without_caching(monkeypatch):
    service = make_active_service()
    proxy = AdditionalProfileProxy(subscription_service=service)

    monkeypatch.setattr(
        "app.web.additional_profile.aiohttp.ClientSession",
        lambda **kwargs: FakeClientSession(
            responses=[
                FakeUpstreamResponse(text=""),
                FakeUpstreamResponse(text="<html>not a profile</html>"),
                FakeUpstreamResponse(status=404),
                ClientError("boom"),
                FakeUpstreamResponse(text="plain text"),
            ],
        ),
    )

    with pytest.raises(web.HTTPBadGateway):
        await proxy.handle(make_request("vpn-allowed"))

    assert proxy._cached_profile is None
