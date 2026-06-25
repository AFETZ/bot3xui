import asyncio
import logging
from dataclasses import dataclass

import aiohttp
from aiohttp import ClientError, ClientTimeout, web

from app.bot.services.subscription import SubscriptionService

logger = logging.getLogger(__name__)

ADDITIONAL_PROFILE_MIRROR_TIMEOUT_SECONDS = 5
ADDITIONAL_PROFILE_TITLE = "AFETZ BS Backup"
ADDITIONAL_PROFILE_UPDATE_INTERVAL_HOURS = "1"
ADDITIONAL_PROFILE_PRIMARY_MIRROR_COUNT = 3
ADDITIONAL_PROFILE_MIRROR_URLS = (
    "https://raw.githubusercontent.com/zieng2/wl/main/vless_universal.txt",
    "https://codeberg.org/zieng2/wl/raw/branch/main/vless_universal.txt",
    "https://gitlab.com/zieng2/wl/raw/main/vless_universal.txt",
    "https://hub.mos.ru/zieng2/wl/raw/main/list_universal.txt",
    "https://gitverse.ru/api/repos/zieng2/wl/raw/branch/master/list_universal.txt",
)
FILTERED_ADDITIONAL_PROFILE_TITLE = "AFETZ BS Recommended"
FILTERED_ADDITIONAL_PROFILE_MIRROR_URLS = (
    "https://raw.githack.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://gitlab.com/igareck/vpn-configs-for-russia/-/raw/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://codeberg.org/igareck/vpn-configs-for-russia/raw/branch/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://bitbucket.org/igareck/vpn-configs-for-russia/raw/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
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


def _redact_identifier(value: str | None) -> str:
    if not value:
        return "-"
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


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


def _build_response_headers(
    snapshot: AdditionalProfileSnapshot,
    *,
    profile_title: str = ADDITIONAL_PROFILE_TITLE,
) -> dict[str, str]:
    return {
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
        "profile-title": profile_title,
        "profile-update-interval": ADDITIONAL_PROFILE_UPDATE_INTERVAL_HOURS,
        "subscription-auto-update-enable": "1",
        "subscription-ping-onopen-enabled": "1",
        "ping-type": "proxy",
        "check-url-via-proxy": "https://cp.cloudflare.com/generate_204",
        # iOS Network Extension memory ceiling workaround — see primary_profile.
        "no-limit-xhttp-enabled": "1",
        "X-Profile-Source": snapshot.source_url,
        "X-Profile-Stale": "1" if snapshot.is_stale else "0",
    }


class AdditionalProfileProxy:
    def __init__(
        self,
        subscription_service: SubscriptionService,
        *,
        mirror_urls: tuple[str, ...] = ADDITIONAL_PROFILE_MIRROR_URLS,
        profile_title: str = ADDITIONAL_PROFILE_TITLE,
        profile_label: str = "additional profile",
    ) -> None:
        self.subscription_service = subscription_service
        self.mirror_urls = mirror_urls
        self.profile_title = profile_title
        self.profile_label = profile_label
        self._cached_profile: AdditionalProfileSnapshot | None = None

    async def _fetch_mirror(
        self,
        session: aiohttp.ClientSession,
        mirror_url: str,
        request_timeout: ClientTimeout,
    ) -> AdditionalProfileSnapshot | None:
        try:
            async with session.get(mirror_url, timeout=request_timeout) as response:
                if response.status != 200:
                    logger.warning(
                        "Additional profile mirror returned bad status: profile=%s url=%s status=%s",
                        self.profile_label,
                        mirror_url,
                        response.status,
                    )
                    return None

                text = await response.text(encoding="utf-8")
        except (asyncio.TimeoutError, ClientError, UnicodeDecodeError) as exception:
            logger.warning(
                "Additional profile mirror fetch failed: profile=%s url=%s error=%s",
                self.profile_label,
                mirror_url,
                exception,
            )
            return None

        if not _looks_like_supported_profile_body(text):
            logger.warning(
                "Additional profile mirror returned invalid profile body: profile=%s url=%s body_len=%d",
                self.profile_label,
                mirror_url,
                len(text),
            )
            return None

        return AdditionalProfileSnapshot(
            text=text,
            source_url=mirror_url,
        )

    async def _fetch_first_available_mirror(
        self,
        session: aiohttp.ClientSession,
        mirror_urls: tuple[str, ...],
        request_timeout: ClientTimeout,
    ) -> AdditionalProfileSnapshot | None:
        tasks = [
            asyncio.create_task(
                self._fetch_mirror(
                    session=session,
                    mirror_url=mirror_url,
                    request_timeout=request_timeout,
                )
            )
            for mirror_url in mirror_urls
        ]

        try:
            for task in asyncio.as_completed(tasks):
                snapshot = await task
                if snapshot:
                    return snapshot
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        return None

    def _mirror_groups(self) -> tuple[tuple[str, ...], ...]:
        primary = self.mirror_urls[:ADDITIONAL_PROFILE_PRIMARY_MIRROR_COUNT]
        fallback = self.mirror_urls[ADDITIONAL_PROFILE_PRIMARY_MIRROR_COUNT:]
        return tuple(group for group in (primary, fallback) if group)

    async def _fetch_profile(self) -> AdditionalProfileSnapshot:
        request_timeout = ClientTimeout(total=ADDITIONAL_PROFILE_MIRROR_TIMEOUT_SECONDS)

        async with aiohttp.ClientSession() as session:
            for mirror_group in self._mirror_groups():
                snapshot = await self._fetch_first_available_mirror(
                    session=session,
                    mirror_urls=mirror_group,
                    request_timeout=request_timeout,
                )
                if not snapshot:
                    continue

                self._cached_profile = snapshot
                return snapshot

        if self._cached_profile:
            logger.warning(
                "All additional profile mirrors failed for %s. Returning stale cached profile from %s.",
                self.profile_label,
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
            logger.info(
                "Additional profile access denied: profile=%s vpn_id=%s user_not_found=True",
                self.profile_label,
                _redact_identifier(vpn_id),
            )
            raise web.HTTPForbidden(text="Forbidden")

        if not status.status_check_ok:
            logger.error(
                "Additional profile status check failed for user %s (profile=%s vpn_id=%s).",
                user.tg_id,
                self.profile_label,
                _redact_identifier(vpn_id),
            )
            raise web.HTTPServiceUnavailable(text="Subscription status is temporarily unavailable.")

        if not status.is_active or not status.has_additional_profile:
            logger.info(
                "Additional profile access denied for user %s (profile=%s vpn_id=%s). active=%s entitled=%s",
                user.tg_id,
                self.profile_label,
                _redact_identifier(vpn_id),
                status.is_active,
                status.has_additional_profile,
            )
            raise web.HTTPForbidden(text="Forbidden")

        snapshot = await self._fetch_profile()

        logger.info(
            "Additional profile access granted for user %s (profile=%s vpn_id=%s source=%s stale=%s).",
            user.tg_id,
            self.profile_label,
            _redact_identifier(vpn_id),
            snapshot.source_url,
            snapshot.is_stale,
        )
        return web.Response(
            text=snapshot.text,
            content_type="text/plain",
            charset="utf-8",
            headers=_build_response_headers(snapshot, profile_title=self.profile_title),
        )


def setup_additional_profile_route(
    app: web.Application,
    subscription_service: SubscriptionService,
) -> None:
    proxy = AdditionalProfileProxy(subscription_service=subscription_service)
    app.router.add_get("/wl/{vpn_id}", proxy.handle)

    filtered_proxy = AdditionalProfileProxy(
        subscription_service=subscription_service,
        mirror_urls=FILTERED_ADDITIONAL_PROFILE_MIRROR_URLS,
        profile_title=FILTERED_ADDITIONAL_PROFILE_TITLE,
        profile_label="filtered additional profile",
    )
    app.router.add_get("/wl-filtered/{vpn_id}", filtered_proxy.handle)
