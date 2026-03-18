"""
One-time script to upgrade existing trial users to 3 devices + whitelist bypass (p3wl).

Run via: docker exec -it 3xui-shop-bot poetry run python /app/migrate_trial_users.py
"""

import asyncio
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.config import load_config
from app.db.models import User

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

TARGET_PLAN_CODE = "p3wl"
TARGET_DEVICES = 3


async def main() -> None:
    config = load_config()
    engine = create_async_engine(config.database.url())
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Import VPN infrastructure
    from app.bot.services.server_pool import ServerPoolService
    from app.bot.services.vpn import VPNService

    server_pool = ServerPoolService(config=config, session=session_factory)
    vpn_service = VPNService(config=config, session=session_factory, server_pool_service=server_pool)

    await server_pool.sync_servers()

    async with session_factory() as session:
        result = await session.execute(
            select(User).where(
                User.is_trial_used == True,
                User.server_id.isnot(None),
            )
        )
        trial_users = result.scalars().all()

    logger.info(f"Found {len(trial_users)} trial users to migrate.")

    success_count = 0
    fail_count = 0

    for user in trial_users:
        logger.info(f"Processing user {user.tg_id} (current plan: {user.current_plan_code})...")

        # Update plan code in DB
        async with session_factory() as session:
            await User.update(session=session, tg_id=user.tg_id, current_plan_code=TARGET_PLAN_CODE)

        # Update device limit on VPN server
        try:
            client_exists = await vpn_service.is_client_exists(user)
            if not client_exists:
                logger.warning(f"  User {user.tg_id} has no VPN client, skipping device update.")
                success_count += 1
                continue

            updated = await vpn_service.update_client(
                user=user,
                devices=TARGET_DEVICES,
                duration=0,  # don't change duration
                replace_devices=True,
                replace_duration=False,
            )

            if updated:
                logger.info(f"  User {user.tg_id}: OK (plan={TARGET_PLAN_CODE}, devices={TARGET_DEVICES})")
                success_count += 1
            else:
                logger.error(f"  User {user.tg_id}: failed to update VPN client")
                fail_count += 1
        except Exception as e:
            logger.error(f"  User {user.tg_id}: error - {e}")
            fail_count += 1

    await engine.dispose()
    logger.info(f"Migration complete. Success: {success_count}, Failed: {fail_count}")


if __name__ == "__main__":
    asyncio.run(main())
