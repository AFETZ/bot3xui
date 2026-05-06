import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.models import SubscriptionData
from app.bot.payment_gateways.gateway_factory import GatewayFactory
from app.bot.utils.constants import TransactionStatus
from app.bot.utils.navigation import NavSubscription
from app.db.models import Transaction

logger = logging.getLogger(__name__)


async def cancel_expired_transactions(
    session_factory: async_sessionmaker,
    expiration_minutes: int = 15,
) -> None:
    session: AsyncSession
    async with session_factory() as session:
        expiration_time = datetime.now(timezone.utc) - timedelta(minutes=expiration_minutes)
        stmt = select(Transaction).where(
            Transaction.status == TransactionStatus.PENDING,
            Transaction.created_at <= expiration_time,
        )
        result = await session.execute(stmt)
        expired_transactions = result.scalars().all()

        if expired_transactions:
            logger.info(
                f"[Background check] Found {len(expired_transactions)} expired transactions."
            )

            for transaction in expired_transactions:
                transaction.status = TransactionStatus.CANCELED
            await session.commit()

            logger.info("[Background check] Successfully canceled expired transactions.")
        else:
            logger.info("[Background check] No expired transactions found.")


async def reconcile_pending_transactions(
    session_factory: async_sessionmaker,
    gateway_factory: GatewayFactory | None,
    lookback_minutes: int = 60,
) -> None:
    if gateway_factory is None:
        return

    session: AsyncSession
    async with session_factory() as session:
        since_time = datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)
        stmt = select(Transaction).where(
            Transaction.status == TransactionStatus.PENDING,
            Transaction.created_at >= since_time,
        )
        result = await session.execute(stmt)
        pending_transactions = result.scalars().all()

    if not pending_transactions:
        return

    logger.info(
        "[Background check] Reconciling %d pending transactions.",
        len(pending_transactions),
    )

    for transaction in pending_transactions:
        try:
            data = SubscriptionData.unpack(transaction.subscription)
        except Exception as exception:
            logger.warning(
                "Skipping transaction %s during reconcile: failed to unpack payload: %s",
                transaction.payment_id,
                exception,
            )
            continue

        if data.state != NavSubscription.PAY_YOOKASSA:
            continue

        try:
            gateway = gateway_factory.get_gateway(data.state)
        except Exception as exception:
            logger.warning(
                "Skipping transaction %s during reconcile: gateway %s unavailable: %s",
                transaction.payment_id,
                data.state,
                exception,
            )
            continue

        try:
            await gateway.reconcile_pending_payment(transaction.payment_id)
        except Exception as exception:
            logger.exception(
                "Pending payment reconcile failed for %s: %s",
                transaction.payment_id,
                exception,
            )

def start_scheduler(
    session: async_sessionmaker,
    gateway_factory: GatewayFactory | None = None,
) -> None:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        reconcile_pending_transactions,
        "interval",
        minutes=1,
        args=[session, gateway_factory],
        next_run_time=datetime.now(),
    )
    scheduler.add_job(
        cancel_expired_transactions,
        "interval",
        minutes=15,
        args=[session],
        next_run_time=datetime.now(),
    )
    scheduler.start()
