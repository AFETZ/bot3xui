"""
Revert incorrectly migrated paid users back to their correct plan.
Only users who have completed transactions (i.e., paid users) will be reverted.
Users with no transactions remain on p3wl (actual trial users).
"""

import asyncio
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.config import load_config
from app.db.models import User, Transaction
from app.bot.models import SubscriptionData

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

MIGRATED_USERS = [
    88019797, 8544768534, 1139776540, 1497941362, 8341832184,
    572618070, 7907401352, 339358590, 609110006, 2124136006, 383925544,
]


async def main() -> None:
    config = load_config()
    engine = create_async_engine(config.database.url())
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    from app.bot.services.server_pool import ServerPoolService
    from app.bot.services.vpn import VPNService

    server_pool = ServerPoolService(config=config, session=session_factory)
    vpn_service = VPNService(config=config, session=session_factory, server_pool_service=server_pool)
    await server_pool.sync_servers()

    for tg_id in MIGRATED_USERS:
        async with session_factory() as session:
            user = await User.get(session=session, tg_id=tg_id)
            if not user:
                logger.warning(f"User {tg_id} not found, skipping.")
                continue

            # Find latest completed transaction
            result = await session.execute(
                select(Transaction)
                .where(
                    Transaction.tg_id == tg_id,
                    Transaction.status == "completed",
                )
                .order_by(Transaction.id.desc())
                .limit(1)
            )
            transaction = result.scalar_one_or_none()

        if not transaction:
            logger.info(f"User {tg_id}: no paid transactions — genuine trial user, keeping p3wl.")
            continue

        # This is a paid user — restore their plan from the transaction
        try:
            data = SubscriptionData.unpack(transaction.subscription)
            original_plan_code = data.plan_code
            original_devices = data.devices
        except Exception as e:
            logger.error(f"User {tg_id}: failed to unpack transaction data: {e}")
            continue

        if not original_plan_code:
            logger.warning(f"User {tg_id}: transaction has no plan_code, devices={original_devices}. Restoring devices only.")
            original_plan_code = f"p{original_devices}"

        logger.info(
            f"User {tg_id}: PAID user — reverting to plan={original_plan_code}, devices={original_devices}"
        )

        # Update DB
        async with session_factory() as session:
            await User.update(session=session, tg_id=tg_id, current_plan_code=original_plan_code)

        # Update VPN server device limit
        try:
            if await vpn_service.is_client_exists(user):
                updated = await vpn_service.update_client(
                    user=user,
                    devices=original_devices,
                    duration=0,
                    replace_devices=True,
                    replace_duration=False,
                )
                if updated:
                    logger.info(f"  User {tg_id}: VPN restored to {original_devices} devices.")
                else:
                    logger.error(f"  User {tg_id}: failed to update VPN client.")
            else:
                logger.info(f"  User {tg_id}: no VPN client, DB updated only.")
        except Exception as e:
            logger.error(f"  User {tg_id}: VPN update error: {e}")

    await engine.dispose()
    logger.info("Revert complete.")


if __name__ == "__main__":
    asyncio.run(main())
