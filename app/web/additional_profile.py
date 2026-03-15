import asyncio
import logging

import aiohttp
from aiohttp import ClientError, ClientTimeout, web

from app.bot.services.subscription import SubscriptionService

logger = logging.getLogger(__name__)

UPSTREAM_ADDITIONAL_PROFILE_URL = (
    "https://raw.githubusercontent.com/zieng2/wl/main/vless_lite.txt"
)


class AdditionalProfileProxy:
    def __init__(self, subscription_service: SubscriptionService) -> None:
        self.subscription_service = subscription_service

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

        try:
            timeout = ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(UPSTREAM_ADDITIONAL_PROFILE_URL) as response:
                    if response.status != 200:
                        logger.error(
                            "Additional profile upstream returned bad status %s for user %s.",
                            response.status,
                            user.tg_id,
                        )
                        raise web.HTTPBadGateway(text="Upstream source is unavailable.")

                    text = await response.text(encoding="utf-8")
        except web.HTTPException:
            raise
        except (asyncio.TimeoutError, ClientError) as exception:
            logger.exception(
                "Additional profile upstream fetch failed for user %s: %s",
                user.tg_id,
                exception,
            )
            raise web.HTTPBadGateway(text="Upstream source is unavailable.") from exception

        logger.info(
            "Additional profile access granted for user %s (vpn_id=%s).",
            user.tg_id,
            vpn_id,
        )
        return web.Response(
            text=text,
            content_type="text/plain",
            charset="utf-8",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )


def setup_additional_profile_route(
    app: web.Application,
    subscription_service: SubscriptionService,
) -> None:
    proxy = AdditionalProfileProxy(subscription_service=subscription_service)
    app.router.add_get("/wl/{vpn_id}", proxy.handle)
