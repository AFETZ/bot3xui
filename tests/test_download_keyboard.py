import base64
import json
from urllib.parse import parse_qs, urlsplit

from app.bot.routers.download.keyboard import (
    build_connect_url,
    build_happ_routing_base64,
    build_happ_routing_connection_url,
)


def test_build_connect_url_uses_happ_scheme_key_and_platform() -> None:
    url = build_connect_url(
        url="https://afzvpn.superbebra.uk",
        scheme="happ://add/",
        key="https://afzvpn.superbebra.uk/sub/user-id",
        platform_param="android",
    )

    parsed = urlsplit(url)
    params = parse_qs(parsed.query)

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        "https://afzvpn.superbebra.uk/connection"
    )
    assert params["scheme"] == ["happ://add/"]
    assert params["key"] == ["https://afzvpn.superbebra.uk/sub/user-id"]
    assert params["platform"] == ["android"]


def test_build_happ_routing_base64_keeps_ru_direct_and_rest_vpn() -> None:
    profile = json.loads(base64.b64decode(build_happ_routing_base64()).decode("utf-8"))

    assert profile["Name"] == "SuperBebra RU Direct"
    assert profile["GlobalProxy"] == "true"
    assert profile["DirectSites"] == ["geosite:CATEGORY-RU"]
    assert "geoip:RU" in profile["DirectIp"]
    assert profile["DomainStrategy"] == "IPIfNonMatch"


def test_build_happ_routing_connection_url_uses_routing_scheme() -> None:
    url = build_happ_routing_connection_url(
        url="https://afzvpn.superbebra.uk",
        platform_param="android",
    )

    parsed = urlsplit(url)
    params = parse_qs(parsed.query)

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        "https://afzvpn.superbebra.uk/connection"
    )
    assert params["scheme"] == ["happ://routing/onadd/"]
    assert params["platform"] == ["android"]
    assert json.loads(base64.b64decode(params["key"][0]).decode("utf-8"))[
        "DirectSites"
    ] == ["geosite:CATEGORY-RU"]
