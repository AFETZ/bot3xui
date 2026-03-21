import logging
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.i18n import gettext as _
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.bot.filters import IsAdmin
from app.bot.utils.constants import TransactionStatus
from app.bot.utils.navigation import NavAdminTools
from app.db.models import Referral, Server, Transaction, User

from .keyboard import statistics_keyboard

logger = logging.getLogger(__name__)
router = Router(name=__name__)


@router.callback_query(F.data == NavAdminTools.STATISTICS, IsAdmin())
async def callback_statistics(
    callback: CallbackQuery, user: User, session: AsyncSession
) -> None:
    logger.info(f"Admin {user.tg_id} opened statistics.")

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    # Total users
    total_users_result = await session.execute(select(func.count(User.id)))
    total_users = total_users_result.scalar() or 0

    # New users today
    new_today_result = await session.execute(
        select(func.count(User.id)).where(User.created_at >= today_start)
    )
    new_today = new_today_result.scalar() or 0

    # New users this week
    new_week_result = await session.execute(
        select(func.count(User.id)).where(User.created_at >= week_ago)
    )
    new_week = new_week_result.scalar() or 0

    # New users this month
    new_month_result = await session.execute(
        select(func.count(User.id)).where(User.created_at >= month_ago)
    )
    new_month = new_month_result.scalar() or 0

    # Active subscribers (have current plan and not expired)
    all_with_sub = await session.execute(
        select(User).where(
            User.current_plan_code.isnot(None),
            User.current_period_started_at.isnot(None),
            User.current_period_duration_days.isnot(None),
        )
    )
    all_sub_users = all_with_sub.scalars().all()
    active_subscribers = sum(
        1 for u in all_sub_users
        if u.current_period_started_at and u.current_period_duration_days
        and (u.current_period_started_at + timedelta(days=u.current_period_duration_days)) > now
    )

    # Trial used count
    trial_result = await session.execute(
        select(func.count(User.id)).where(User.is_trial_used == True)
    )
    trial_used = trial_result.scalar() or 0

    # Total completed transactions
    completed_tx_result = await session.execute(
        select(func.count(Transaction.id)).where(
            Transaction.status == TransactionStatus.COMPLETED
        )
    )
    completed_transactions = completed_tx_result.scalar() or 0

    # Transactions today
    tx_today_result = await session.execute(
        select(func.count(Transaction.id)).where(
            Transaction.status == TransactionStatus.COMPLETED,
            Transaction.created_at >= today_start,
        )
    )
    tx_today = tx_today_result.scalar() or 0

    # Transactions this week
    tx_week_result = await session.execute(
        select(func.count(Transaction.id)).where(
            Transaction.status == TransactionStatus.COMPLETED,
            Transaction.created_at >= week_ago,
        )
    )
    tx_week = tx_week_result.scalar() or 0

    # Transactions this month
    tx_month_result = await session.execute(
        select(func.count(Transaction.id)).where(
            Transaction.status == TransactionStatus.COMPLETED,
            Transaction.created_at >= month_ago,
        )
    )
    tx_month = tx_month_result.scalar() or 0

    # Servers stats
    servers = await Server.get_all(session)
    total_servers = len(servers)
    online_servers = sum(1 for s in servers if s.online)
    total_capacity = sum(s.max_clients for s in servers)
    total_connected = sum(s.current_clients for s in servers)

    # Referrals count
    referrals_result = await session.execute(select(func.count(Referral.id)))
    total_referrals = referrals_result.scalar() or 0

    text = _("statistics:message:main").format(
        total_users=total_users,
        new_today=new_today,
        new_week=new_week,
        new_month=new_month,
        active_subscribers=active_subscribers,
        trial_used=trial_used,
        completed_transactions=completed_transactions,
        tx_today=tx_today,
        tx_week=tx_week,
        tx_month=tx_month,
        total_servers=total_servers,
        online_servers=online_servers,
        total_capacity=total_capacity,
        total_connected=total_connected,
        total_referrals=total_referrals,
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=statistics_keyboard(),
    )
