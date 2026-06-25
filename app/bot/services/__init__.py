from aiogram import Bot
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.models import ServicesContainer
from app.config import Config

_SERVICE_EXPORTS = {
    "AdminStatisticsService": "admin_statistics",
    "AdminUserService": "admin_users",
    "InviteStatsService": "invite_stats",
    "NotificationService": "notification",
    "PaymentStatsService": "payment_stats",
    "PlanService": "plan",
    "ReferralService": "referral",
    "ServerPoolService": "server_pool",
    "SubscriptionService": "subscription",
    "VPNService": "vpn",
}

__all__ = [
    "ServicesContainer",
    "initialize",
    *_SERVICE_EXPORTS,
]


def __getattr__(name: str):
    if name not in _SERVICE_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from importlib import import_module

    module = import_module(f"{__name__}.{_SERVICE_EXPORTS[name]}")
    service = getattr(module, name)
    globals()[name] = service
    return service


async def initialize(
    config: Config,
    session: async_sessionmaker,
    bot: Bot,
) -> ServicesContainer:
    from .admin_statistics import AdminStatisticsService
    from .admin_users import AdminUserService
    from .invite_stats import InviteStatsService
    from .notification import NotificationService
    from .payment_stats import PaymentStatsService
    from .plan import PlanService
    from .referral import ReferralService
    from .server_pool import ServerPoolService
    from .subscription import SubscriptionService
    from .vpn import VPNService

    server_pool = ServerPoolService(config=config, session=session)
    plan = PlanService()
    vpn = VPNService(config=config, session=session, server_pool_service=server_pool)
    notification = NotificationService(config=config, bot=bot)
    referral = ReferralService(config=config, session_factory=session, vpn_service=vpn)
    subscription = SubscriptionService(
        config=config,
        session_factory=session,
        vpn_service=vpn,
        plan_service=plan,
    )
    payment_stats = PaymentStatsService(session_factory=session)
    invite_stats = InviteStatsService(session_factory=session, payment_stats_service=payment_stats)
    admin_statistics = AdminStatisticsService(
        session_factory=session,
        payment_stats_service=payment_stats,
    )
    admin_users = AdminUserService(
        session_factory=session,
        subscription_service=subscription,
        payment_stats_service=payment_stats,
    )

    return ServicesContainer(
        server_pool=server_pool,
        plan=plan,
        vpn=vpn,
        notification=notification,
        referral=referral,
        subscription=subscription,
        payment_stats=payment_stats,
        invite_stats=invite_stats,
        admin_statistics=admin_statistics,
        admin_users=admin_users,
    )
