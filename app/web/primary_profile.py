import asyncio
import base64
import json
import logging
from dataclasses import dataclass
from urllib.parse import quote, urlsplit, urlunsplit

import aiohttp
from aiohttp import ClientError, ClientTimeout, web

from app.bot.services.subscription import SubscriptionService

logger = logging.getLogger(__name__)

PROFILE_TITLE_PREFIX = "AFZVPN"
PROFILE_AGGREGATED_TITLE = PROFILE_TITLE_PREFIX
PROFILE_SERVER_LABELS = {
    "FI": "Finland",
    "FINLAND": "Finland",
    "KZ": "Kazakhstan",
    "KAZAKHSTAN": "Kazakhstan",
}
FORWARDED_HEADERS = (
    "content-type",
    "profile-title",
    "profile-update-interval",
    "profile-web-page-url",
    "support-url",
    "announce",
    "subscription-userinfo",
)

SUPPORTED_PROFILE_PREFIXES = (
    "vless://",
    "vmess://",
    "trojan://",
    "ss://",
    "socks://",
    "hy2://",
    "hysteria2://",
    "#",
)
PROFILE_NODE_PREFIXES = tuple(prefix for prefix in SUPPORTED_PROFILE_PREFIXES if prefix != "#")


@dataclass(frozen=True)
class UpstreamProfileSnapshot:
    server: object
    url: str
    body_bytes: bytes
    headers: dict[str, str]


def _looks_like_supported_profile_body(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    return all(line.startswith(SUPPORTED_PROFILE_PREFIXES) for line in lines)


def _maybe_decode_base64_profile(body_bytes: bytes) -> bytes:
    try:
        encoded = body_bytes.decode("ascii").strip()
    except UnicodeDecodeError:
        return body_bytes

    if not encoded:
        return body_bytes

    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return body_bytes

    if not _looks_like_supported_profile_body(decoded):
        return body_bytes

    return decoded.encode("utf-8")


def _normalize_forwarded_headers(upstream_headers: dict[str, str]) -> dict[str, str]:
    response_headers = {}
    for name in FORWARDED_HEADERS:
        value = upstream_headers.get(name)
        if not value:
            continue

        # Some 3x-ui variants emit an empty base64 marker which newer Happ builds
        # can treat as malformed metadata.
        if name == "profile-title" and value.strip().lower() == "base64:":
            continue

        response_headers[name] = value

    return response_headers


def _safe_profile_title_value(value: str) -> str | None:
    title = value.encode("ascii", errors="ignore").decode("ascii").strip()
    return title or None


def _server_label(server) -> str | None:
    if not server:
        return None

    location = (getattr(server, "location", "") or "").upper()
    return (
        PROFILE_SERVER_LABELS.get(location)
        or getattr(server, "name", None)
        or getattr(server, "location", None)
    )


def _build_profile_title_for_server(server) -> str | None:
    label = _server_label(server)
    if not label:
        return None

    return _safe_profile_title_value(f"{PROFILE_TITLE_PREFIX} {label}")


def _build_profile_title(user) -> str | None:
    return _build_profile_title_for_server(getattr(user, "server", None))


def _base64_decode_padded(value: str) -> bytes:
    padded = value + ("=" * (-len(value) % 4))
    return base64.b64decode(padded)


def _rename_vmess_profile(line: str, title: str) -> str:
    payload = line[len("vmess://") :]
    try:
        decoded = _base64_decode_padded(payload).decode("utf-8")
        data = json.loads(decoded)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return line

    if not isinstance(data, dict):
        return line

    data["ps"] = title
    encoded = base64.b64encode(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return f"vmess://{encoded}"


def _rename_uri_profile(line: str, title: str) -> str:
    try:
        parts = urlsplit(line)
    except ValueError:
        return line

    if not parts.scheme:
        return line

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            parts.query,
            quote(title, safe=""),
        )
    )


def _rename_profile_line(line: str, server) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if not stripped.startswith(PROFILE_NODE_PREFIXES):
        return None

    title = _build_profile_title_for_server(server) or PROFILE_TITLE_PREFIX
    if stripped.startswith("vmess://"):
        return _rename_vmess_profile(stripped, title)
    return _rename_uri_profile(stripped, title)


def _extract_profile_lines(body_bytes: bytes, server) -> list[str]:
    normalized_body = _maybe_decode_base64_profile(body_bytes)
    try:
        text = normalized_body.decode("utf-8")
    except UnicodeDecodeError:
        return []

    lines: list[str] = []
    for line in text.splitlines():
        renamed = _rename_profile_line(line, server)
        if renamed:
            lines.append(renamed)
    return lines


def _build_aggregated_profile_body(snapshots: list[UpstreamProfileSnapshot]) -> bytes:
    lines: list[str] = []
    seen: set[str] = set()

    for snapshot in snapshots:
        for line in _extract_profile_lines(snapshot.body_bytes, snapshot.server):
            if line in seen:
                continue
            seen.add(line)
            lines.append(line)

    if not lines:
        return b""
    return ("\n".join(lines) + "\n").encode("utf-8")


def _build_cabinet_url(subscription_service: SubscriptionService, user) -> str | None:
    get_cabinet_url = getattr(subscription_service, "get_cabinet_url", None)
    if not get_cabinet_url:
        return None
    return get_cabinet_url(user)


def _build_inactive_profile_response(
    subscription_service: SubscriptionService,
    user,
) -> web.Response:
    cabinet_url = _build_cabinet_url(subscription_service, user)
    headers = {
        "content-type": "text/plain; charset=utf-8",
        "cache-control": "no-store, no-cache, must-revalidate",
        "pragma": "no-cache",
        "expires": "0",
        "profile-title": f"{PROFILE_TITLE_PREFIX} Expired",
    }
    if cabinet_url:
        headers["profile-web-page-url"] = cabinet_url
        headers["support-url"] = cabinet_url
        headers["announce"] = f"Subscription expired. Renew: {cabinet_url}"

    text = "# Subscription expired\n"
    if cabinet_url:
        text += f"# Renew: {cabinet_url}\n"
    return web.Response(text=text, headers=headers)


class PrimaryProfileProxy:
    def __init__(self, subscription_service: SubscriptionService) -> None:
        self.subscription_service = subscription_service

    async def _fetch_profile_source(
        self,
        session: aiohttp.ClientSession,
        source,
        user,
        user_agent: str,
    ) -> UpstreamProfileSnapshot | None:
        source_url = getattr(source, "url", "")
        source_server = getattr(source, "server", None)
        if not source_url or not source_server:
            return None

        try:
            async with session.get(
                source_url,
                ssl=False,
                headers={"User-Agent": user_agent or "Happ"},
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "Primary profile upstream returned bad status %s for user %s server=%s.",
                        response.status,
                        user.tg_id,
                        getattr(source_server, "name", "?"),
                    )
                    return None

                body_bytes = await response.read()
                upstream_headers = {
                    name.lower(): value for name, value in response.headers.items()
                }
        except (asyncio.TimeoutError, ClientError) as exception:
            logger.warning(
                "Primary profile upstream fetch failed for user %s server=%s: %s",
                user.tg_id,
                getattr(source_server, "name", "?"),
                exception,
            )
            return None

        return UpstreamProfileSnapshot(
            server=source_server,
            url=source_url,
            body_bytes=body_bytes,
            headers=upstream_headers,
        )

    async def _handle_profile_sources(
        self,
        *,
        sources,
        user,
        vpn_id: str,
        user_agent: str,
    ) -> web.Response:
        timeout = ClientTimeout(total=15)
        snapshots: list[UpstreamProfileSnapshot] = []

        async with aiohttp.ClientSession(timeout=timeout) as session:
            for source in sources:
                snapshot = await self._fetch_profile_source(
                    session=session,
                    source=source,
                    user=user,
                    user_agent=user_agent,
                )
                if snapshot:
                    snapshots.append(snapshot)

        if not snapshots:
            logger.error("Primary profile upstream sources are unavailable for user %s.", user.tg_id)
            raise web.HTTPBadGateway(text="Upstream source is unavailable.")

        body = _build_aggregated_profile_body(snapshots)
        if not body:
            logger.error("Primary profile upstream sources returned no supported nodes for user %s.", user.tg_id)
            raise web.HTTPBadGateway(text="Upstream source is unavailable.")

        logger.info(
            "Primary profile access granted: tg_id=%s vpn_id=%s ua=%r sources=%d body_len=%d",
            user.tg_id,
            vpn_id,
            user_agent,
            len(snapshots),
            len(body),
        )

        response_headers = _normalize_forwarded_headers(snapshots[0].headers)
        response_headers["profile-title"] = PROFILE_AGGREGATED_TITLE
        response_headers["profile-update-interval"] = "1"
        response_headers["subscription-auto-update-enable"] = "1"
        response_headers["subscription-ping-onopen-enabled"] = "1"
        response_headers["ping-type"] = "proxy-head"
        response_headers["check-url-via-proxy"] = "https://cp.cloudflare.com/generate_204"

        cabinet_url = _build_cabinet_url(self.subscription_service, user)
        if cabinet_url:
            response_headers["profile-web-page-url"] = cabinet_url
            response_headers["support-url"] = cabinet_url

        response_headers["content-type"] = "text/plain; charset=utf-8"
        response_headers["cache-control"] = "no-store, no-cache, must-revalidate"
        response_headers["pragma"] = "no-cache"
        response_headers["expires"] = "0"

        return web.Response(body=body, headers=response_headers)

    async def handle(self, request: web.Request) -> web.StreamResponse:
        vpn_id = request.match_info["vpn_id"]
        user_agent = request.headers.get("User-Agent", "")
        client_ip = request.headers.get("X-Forwarded-For") or request.headers.get(
            "CF-Connecting-IP"
        ) or (request.remote or "?")

        logger.info(
            "Primary profile request: vpn_id=%s ua=%r ip=%s",
            vpn_id,
            user_agent,
            client_ip,
        )

        user, status = await self.subscription_service.get_subscription_status_by_vpn_id(
            vpn_id
        )

        if not user or not status:
            logger.info("Primary profile access denied: vpn_id=%s user_not_found=True", vpn_id)
            raise web.HTTPForbidden(text="Forbidden")

        if not status.status_check_ok:
            logger.error(
                "Primary profile status check failed for user %s (vpn_id=%s).",
                user.tg_id,
                vpn_id,
            )
            raise web.HTTPServiceUnavailable(
                text="Subscription status is temporarily unavailable."
            )

        if not status.is_active:
            logger.info(
                "Primary profile inactive for user %s (vpn_id=%s). Returning renewal profile.",
                user.tg_id,
                vpn_id,
            )
            return _build_inactive_profile_response(self.subscription_service, user)

        get_upstream_profile_sources = getattr(
            self.subscription_service,
            "get_upstream_profile_sources",
            None,
        )
        if get_upstream_profile_sources:
            sources = await get_upstream_profile_sources(user)
            if sources:
                return await self._handle_profile_sources(
                    sources=sources,
                    user=user,
                    vpn_id=vpn_id,
                    user_agent=user_agent,
                )

        upstream_url = await self.subscription_service.get_upstream_profile_url(user)
        if not upstream_url:
            logger.error("Primary profile upstream URL is missing for user %s.", user.tg_id)
            raise web.HTTPBadGateway(text="Upstream source is unavailable.")

        try:
            timeout = ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    upstream_url,
                    ssl=False,
                    headers={"User-Agent": user_agent or "Happ"},
                ) as response:
                    if response.status != 200:
                        logger.error(
                            "Primary profile upstream returned bad status %s for user %s.",
                            response.status,
                            user.tg_id,
                        )
                        raise web.HTTPBadGateway(text="Upstream source is unavailable.")

                    body_bytes = await response.read()
                    upstream_headers = {
                        name.lower(): value for name, value in response.headers.items()
                    }
        except web.HTTPException:
            raise
        except (asyncio.TimeoutError, ClientError) as exception:
            logger.exception(
                "Primary profile upstream fetch failed for user %s: %s",
                user.tg_id,
                exception,
            )
            raise web.HTTPBadGateway(text="Upstream source is unavailable.") from exception

        logger.info(
            "Primary profile access granted: tg_id=%s vpn_id=%s ua=%r body_len=%d title=%r ui=%r",
            user.tg_id,
            vpn_id,
            user_agent,
            len(body_bytes),
            upstream_headers.get("profile-title"),
            upstream_headers.get("subscription-userinfo"),
        )

        normalized_body = _maybe_decode_base64_profile(body_bytes)
        response_headers = _normalize_forwarded_headers(upstream_headers)
        profile_title = _build_profile_title(user)
        if profile_title:
            response_headers["profile-title"] = profile_title
        cabinet_url = _build_cabinet_url(self.subscription_service, user)
        if cabinet_url:
            response_headers["profile-web-page-url"] = cabinet_url
            response_headers["support-url"] = cabinet_url

        response_headers.setdefault("content-type", "text/plain; charset=utf-8")
        response_headers["cache-control"] = "no-store, no-cache, must-revalidate"
        response_headers["pragma"] = "no-cache"
        response_headers["expires"] = "0"

        return web.Response(body=normalized_body, headers=response_headers)


def setup_primary_profile_route(
    app: web.Application,
    subscription_service: SubscriptionService,
) -> None:
    proxy = PrimaryProfileProxy(subscription_service=subscription_service)
    app.router.add_get("/sub/{vpn_id}", proxy.handle)
