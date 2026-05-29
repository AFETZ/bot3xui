import asyncio
import logging
from dataclasses import dataclass

import aiohttp
from aiohttp import ClientError, ClientTimeout, web

from app.bot.services.subscription import SubscriptionService

logger = logging.getLogger(__name__)

ADDITIONAL_PROFILE_MIRROR_TIMEOUT_SECONDS = 5
ADDITIONAL_PROFILE_TITLE = "AFZVPN Universal WL"
ADDITIONAL_PROFILE_MIRROR_URLS = (
    "https://raw.githubusercontent.com/zieng2/wl/main/vless_universal.txt",
    "https://codeberg.org/zieng2/wl/raw/branch/main/vless_universal.txt",
    "https://gitlab.com/zieng2/wl/raw/main/vless_universal.txt",
    "https://hub.mos.ru/zieng2/wl/raw/main/list_universal.txt",
    "https://gitverse.ru/api/repos/zieng2/wl/raw/branch/master/list_universal.txt",
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


@dataclass(frozen=True)
class AdditionalProfileSnapshot:
    text: str
    source_url: str
    is_stale: bool = False


def _looks_like_supported_profile_body(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    return all(line.startswith(SUPPORTED_PROFILE_PREFIXES) for line in lines)


def _build_response_headers(snapshot: AdditionalProfileSnapshot) -> dict[str, str]:
    return {
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
        "profile-title": ADDITIONAL_PROFILE_TITLE,
        "profile-update-interval": "1",
        "subscription-auto-update-enable": "1",
        "subscription-ping-onopen-enabled": "1",
        "ping-type": "proxy-head",
        "check-url-via-proxy": "https://cp.cloudflare.com/generate_204",
        "X-Profile-Source": snapshot.source_url,
        "X-Profile-Stale": "1" if snapshot.is_stale else "0",
    }


class AdditionalProfileProxy:
    def __init__(self, subscription_service: SubscriptionService) -> None:
        self.subscription_service = subscription_service
        self._cached_profile: AdditionalProfileSnapshot | None = None

    async def _fetch_profile(self) -> AdditionalProfileSnapshot:
        request_timeout = ClientTimeout(total=ADDITIONAL_PROFILE_MIRROR_TIMEOUT_SECONDS)

        async with aiohttp.ClientSession() as session:
            for mirror_url in ADDITIONAL_PROFILE_MIRROR_URLS:
                try:
                    async with session.get(mirror_url, timeout=request_timeout) as response:
                        if response.status != 200:
                            logger.warning(
                                "Additional profile mirror returned bad status: url=%s status=%s",
                                mirror_url,
                                response.status,
                            )
                            continue

                        text = await response.text(encoding="utf-8")
                except (asyncio.TimeoutError, ClientError, UnicodeDecodeError) as exception:
                    logger.warning(
                        "Additional profile mirror fetch failed: url=%s error=%s",
                        mirror_url,
                        exception,
                    )
                    continue

                if not _looks_like_supported_profile_body(text):
                    logger.warning(
                        "Additional profile mirror returned invalid profile body: url=%s body_len=%d",
                        mirror_url,
                        len(text),
                    )
                    continue

                snapshot = AdditionalProfileSnapshot(
                    text=text,
                    source_url=mirror_url,
                )
                self._cached_profile = snapshot
                return snapshot

        if self._cached_profile:
            logger.warning(
                "All additional profile mirrors failed. Returning stale cached profile from %s.",
                self._cached_profile.source_url,
            )
            return AdditionalProfileSnapshot(
                text=self._cached_profile.text,
                source_url=self._cached_profile.source_url,
                is_stale=True,
            )

        raise web.HTTPBadGateway(text="Upstream source is unavailable.")

    async def handle(self, request: web.Request) -> web.Response:
        vpn_id = request.match_info["vpn_id"]
        user, status = await self.subscription_service.get_subscription_status_by_vpn_id(vpn_id)

        if not user or not status:
            logger.info("Additional profile access denied: vpn_id=%s user_not_found=True", vpn_id)
            raise web.HTTPForbidden(text="Forbidden")

        if not status.status_check_ok:
            logger.error(
                "Additional profile status check failed for user %s (vpn_id=%s).",
                user.tg_id,
                vpn_id,
            )
            raise web.HTTPServiceUnavailable(text="Subscription status is temporarily unavailable.")

        if not status.is_active or not status.has_additional_profile:
            logger.info(
                "Additional profile access denied for user %s (vpn_id=%s). active=%s entitled=%s",
                user.tg_id,
                vpn_id,
                status.is_active,
                status.has_additional_profile,
            )
            raise web.HTTPForbidden(text="Forbidden")

        snapshot = await self._fetch_profile()

        logger.info(
            "Additional profile access granted for user %s (vpn_id=%s source=%s stale=%s).",
            user.tg_id,
            vpn_id,
            snapshot.source_url,
            snapshot.is_stale,
        )
        return web.Response(
            text=snapshot.text,
            content_type="text/plain",
            charset="utf-8",
            headers=_build_response_headers(snapshot),
        )


def setup_additional_profile_route(
    app: web.Application,
    subscription_service: SubscriptionService,
) -> None:
    proxy = AdditionalProfileProxy(subscription_service=subscription_service)
    app.router.add_get("/wl/{vpn_id}", proxy.handle)
