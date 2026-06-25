import logging
import time
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from redis.asyncio.client import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.services.job_locks import RedisJobLock
from app.bot.services.runtime_metrics import runtime_metrics
from app.bot.services import ReferralService
from app.db.models import ReferrerReward

logger = logging.getLogger(__name__)


async def reward_pending_referrals_after_payment(
    session_factory: async_sessionmaker,
    referral_service: ReferralService,
) -> None:
    started_at = time.monotonic()
    session: AsyncSession
    async with session_factory() as session:
        stmt = select(ReferrerReward).where(ReferrerReward.rewarded_at.is_(None))
        result = await session.execute(stmt)
        pending_rewards = result.scalars().all()

        logger.info(f"[Background check] Found {len(pending_rewards)} not proceed rewards.")

        for reward in pending_rewards:
            success = await referral_service.process_referrer_rewards_after_payment(reward=reward)
            if not success:
                logger.warning(
                    f"[Background check] Reward {reward.id} was NOT proceed successfully."
                )

        logger.info("[Background check] Referrer rewards check finished.")

    runtime_metrics.record_event(
        "referrals.rewards.last_run",
        pending=len(pending_rewards),
    )
    runtime_metrics.record_duration("referrals.rewards.duration_seconds", started_at)


async def reward_pending_referrals_after_payment_locked(
    session_factory: async_sessionmaker,
    referral_service: ReferralService,
    redis: Redis,
) -> None:
    async with RedisJobLock(redis, "job:referral_rewards", 14 * 60) as acquired:
        if not acquired:
            logger.info("[Background check] Referrer rewards check already running.")
            return
        await reward_pending_referrals_after_payment(
            session_factory=session_factory,
            referral_service=referral_service,
        )


def start_scheduler(
    session_factory: async_sessionmaker,
    referral_service: ReferralService,
    redis: Redis | None = None,
) -> None:
    scheduler = AsyncIOScheduler()
    job = reward_pending_referrals_after_payment_locked if redis else reward_pending_referrals_after_payment
    args = [session_factory, referral_service, redis] if redis else [session_factory, referral_service]
    scheduler.add_job(
        job,
        "interval",
        minutes=15,
        args=args,
        next_run_time=datetime.now(),
    )
    scheduler.start()
