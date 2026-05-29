import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from aiogram.utils.i18n import I18n
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from redis.asyncio.client import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.services import NotificationService, VPNService
from app.db.models import User

logger = logging.getLogger(__name__)

EXPIRY_NOTIFICATION_TTL = timedelta(days=2)


@dataclass(frozen=True)
class ExpiryNotificationThreshold:
    name: str
    window: timedelta
    message_key: str


EXPIRY_NOTIFICATION_THRESHOLDS = (
    ExpiryNotificationThreshold(
        name="3h",
        window=timedelta(hours=3),
        message_key="task:message:subscription_expiry_urgent",
    ),
    ExpiryNotificationThreshold(
        name="24h",
        window=timedelta(hours=24),
        message_key="task:message:subscription_expiry",
    ),
)


def _select_expiry_notification(
    time_left: timedelta,
) -> ExpiryNotificationThreshold | None:
    if time_left <= timedelta(0):
        return None

    for threshold in EXPIRY_NOTIFICATION_THRESHOLDS:
        if time_left <= threshold.window:
            return threshold

    return None


def _expiry_notification_key(
    tg_id: int,
    expiry_time: int,
    threshold: ExpiryNotificationThreshold,
) -> str:
    return (
        f"user:notified:subscription_expiry:{tg_id}:{expiry_time}:{threshold.name}"
    )


def _legacy_expiry_notification_key(tg_id: int) -> str:
    return f"user:notified:{tg_id}"


async def notify_users_with_expiring_subscription(
    session_factory: async_sessionmaker,
    redis: Redis,
    i18n: I18n,
    vpn_service: VPNService,
    notification_service: NotificationService,
) -> None:
    session: AsyncSession
    async with session_factory() as session:
        users = await User.get_all(session=session)

        logger.info(
            f"[Background task] Starting subscription expiration check for {len(users)} users."
        )

        for user in users:
            client_data = await vpn_service.get_client_data(user)

            # Skip if no client data or subscription is unlimited
            if not client_data or client_data._expiry_time == -1:
                continue

            now = datetime.now(timezone.utc)
            expiry_datetime = datetime.fromtimestamp(
                client_data._expiry_time / 1000, timezone.utc
            )
            time_left = expiry_datetime - now

            threshold = _select_expiry_notification(time_left)
            if threshold is None:
                continue

            user_notified_key = _expiry_notification_key(
                user.tg_id,
                client_data._expiry_time,
                threshold,
            )

            # Check if user was already notified for this expiry timestamp.
            if await redis.get(user_notified_key):
                continue

            if (
                threshold.name == "24h"
                and await redis.get(_legacy_expiry_notification_key(user.tg_id))
            ):
                continue

            # BUG: The button and expiry_time will not be translated
            # (the translation logic needs to be changed outside the current context)
            await notification_service.notify_by_id(
                chat_id=user.tg_id,
                text=i18n.gettext(
                    threshold.message_key,
                    locale=user.language_code,
                ).format(
                    devices=client_data.max_devices,
                    expiry_time=client_data.expiry_time,
                ),
                # reply_markup=keyboard_extend
            )

            await redis.set(user_notified_key, "true", ex=EXPIRY_NOTIFICATION_TTL)
            logger.info(
                "[Background task] Sent %s expiry notification to user %s.",
                threshold.name,
                user.tg_id,
            )
        logger.info("[Background task] Subscription check finished.")


def start_scheduler(
    session_factory: async_sessionmaker,
    redis: Redis,
    i18n: I18n,
    vpn_service: VPNService,
    notification_service: NotificationService,
) -> None:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        notify_users_with_expiring_subscription,
        "interval",
        minutes=15,
        args=[session_factory, redis, i18n, vpn_service, notification_service],
        next_run_time=datetime.now(tz=timezone.utc),
    )
    scheduler.start()
