"""
Manually activate subscription for user 1733231444 whose payment
316f292b-000f-5001-9000-13defbd6678d succeeded in YooKassa but was
not processed due to auto-cancel race condition.

Plan: p1 (1 device, 30 days, 299 RUB)

Usage:
    docker exec -it 3xui-shop-bot poetry run python /app/fix_user_1733231444.py
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.bot.utils.constants import TransactionStatus
from app.config import load_config
from app.db.models import Transaction, User

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# === Configuration ===
TARGET_TG_ID = 1733231444
PAYMENT_ID = "316f292b-000f-5001-9000-13defbd6678d"
PLAN_CODE = "p1"
DEVICES = 1
DURATION_DAYS = 30
# =====================


async def main() -> None:
    config = load_config()
    engine = create_async_engine(config.database.url())
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    from app.bot.services.server_pool import ServerPoolService
    from app.bot.services.vpn import VPNService

    server_pool = ServerPoolService(config=config, session=session_factory)
    vpn_service = VPNService(config=config, session=session_factory, server_pool_service=server_pool)
    await server_pool.sync_servers()

    async with session_factory() as session:
        user = await User.get(session=session, tg_id=TARGET_TG_ID)

    if not user:
        logger.error(f"User {TARGET_TG_ID} not found.")
        await engine.dispose()
        return

    logger.info(
        f"User {TARGET_TG_ID} found. server_id={user.server_id}, "
        f"current_plan={user.current_plan_code}"
    )

    # Activate VPN subscription (create or update client)
    client = await vpn_service.is_client_exists(user)
    if client:
        logger.info(f"Client exists, updating with {DEVICES} device(s) and {DURATION_DAYS} days.")
        success = await vpn_service.update_client(
            user=user,
            devices=DEVICES,
            duration=DURATION_DAYS,
            replace_devices=True,
            replace_duration=True,
        )
    else:
        logger.info(f"Client does not exist, creating with {DEVICES} device(s) and {DURATION_DAYS} days.")
        success = await vpn_service.create_client(
            user=user,
            devices=DEVICES,
            duration=DURATION_DAYS,
        )

    if not success:
        logger.error(f"Failed to activate VPN subscription for user {TARGET_TG_ID}.")
        await engine.dispose()
        return

    logger.info("VPN subscription activated successfully.")

    # Update plan code and period in DB
    async with session_factory() as session:
        await User.update(
            session=session,
            tg_id=TARGET_TG_ID,
            current_plan_code=PLAN_CODE,
            current_period_started_at=datetime.now(timezone.utc),
            current_period_duration_days=DURATION_DAYS,
        )

    logger.info(f"User {TARGET_TG_ID} plan updated to {PLAN_CODE}, period={DURATION_DAYS} days.")

    # Update transaction status to completed
    async with session_factory() as session:
        await Transaction.update(
            session=session,
            payment_id=PAYMENT_ID,
            status=TransactionStatus.COMPLETED,
        )

    logger.info(f"Transaction {PAYMENT_ID} marked as completed.")
    logger.info("Done!")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
