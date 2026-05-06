from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.models import AdminStatisticsOverview
from app.bot.services.payment_stats import PaymentStatsService
from app.bot.utils.constants import TransactionStatus
from app.db.models import Referral, Server, Transaction, User

logger = logging.getLogger(__name__)


class AdminStatisticsService:
    def __init__(
        self,
        session_factory: async_sessionmaker,
        payment_stats_service: PaymentStatsService,
    ) -> None:
        self.session_factory = session_factory
        self.payment_stats = payment_stats_service
        logger.debug("AdminStatisticsService initialized")

    @staticmethod
    def get_period_start(period_code: str, now: datetime | None = None) -> datetime | None:
        now = now or datetime.utcnow()
        if period_code == "today":
            return now.replace(hour=0, minute=0, second=0, microsecond=0)
        if period_code == "7d":
            return now - timedelta(days=7)
        if period_code == "30d":
            return now - timedelta(days=30)
        return None

    async def get_overview(
        self,
        *,
        period_code: str,
        session: Optional[AsyncSession] = None,
        payment_method_currencies: Optional[dict[str, str]] = None,
    ) -> AdminStatisticsOverview:
        async def _get_overview(s: AsyncSession) -> AdminStatisticsOverview:
            now = datetime.utcnow()
            period_start = self.get_period_start(period_code, now=now)

            paid_tg_ids_subq = (
                select(Transaction.tg_id)
                .where(Transaction.status == TransactionStatus.COMPLETED)
                .distinct()
            )

            total_users = (await s.execute(select(func.count(User.id)))).scalar() or 0
            new_users_query = select(func.count(User.id))
            if period_start is not None:
                new_users_query = new_users_query.where(User.created_at >= period_start)
            new_users = (await s.execute(new_users_query)).scalar() or 0

            paid_users_total = (
                await s.execute(
                    select(func.count(func.distinct(User.tg_id))).where(User.tg_id.in_(paid_tg_ids_subq))
                )
            ).scalar() or 0

            current_paid_users = (
                await s.execute(
                    select(func.count(User.id)).where(
                        User.current_plan_code.isnot(None),
                        User.tg_id.in_(paid_tg_ids_subq),
                    )
                )
            ).scalar() or 0

            current_trial_users = (
                await s.execute(
                    select(func.count(User.id)).where(
                        User.current_plan_code.isnot(None),
                        User.tg_id.notin_(paid_tg_ids_subq),
                    )
                )
            ).scalar() or 0

            inactive_paid_users = (
                await s.execute(
                    select(func.count(User.id)).where(
                        User.current_plan_code.is_(None),
                        User.tg_id.in_(paid_tg_ids_subq),
                    )
                )
            ).scalar() or 0

            inactive_free_users = (
                await s.execute(
                    select(func.count(User.id)).where(
                        User.current_plan_code.is_(None),
                        User.tg_id.notin_(paid_tg_ids_subq),
                    )
                )
            ).scalar() or 0

            trial_used_total = (
                await s.execute(select(func.count(User.id)).where(User.is_trial_used == True))
            ).scalar() or 0

            completed_transactions_total = (
                await s.execute(
                    select(func.count(Transaction.id)).where(
                        Transaction.status == TransactionStatus.COMPLETED
                    )
                )
            ).scalar() or 0

            completed_transactions_period_query = select(func.count(Transaction.id)).where(
                Transaction.status == TransactionStatus.COMPLETED
            )
            if period_start is not None:
                completed_transactions_period_query = completed_transactions_period_query.where(
                    Transaction.created_at >= period_start
                )
            completed_transactions_period = (
                await s.execute(completed_transactions_period_query)
            ).scalar() or 0

            revenue_period = await self.payment_stats.get_total_revenue_stats(
                session=s,
                payment_method_currencies=payment_method_currencies,
                since=period_start,
            )

            servers = await Server.get_all(s)
            total_servers = len(servers)
            online_servers = sum(1 for server in servers if server.online)
            total_capacity = sum(server.max_clients for server in servers)
            total_connected = sum(server.current_clients for server in servers)

            total_referrals = (await s.execute(select(func.count(Referral.id)))).scalar() or 0
            referrals_period_query = select(func.count(Referral.id))
            if period_start is not None:
                referrals_period_query = referrals_period_query.where(
                    Referral.created_at >= period_start
                )
            referrals_period = (await s.execute(referrals_period_query)).scalar() or 0

            return AdminStatisticsOverview(
                period_code=period_code,  # type: ignore[arg-type]
                generated_at=now,
                total_users=total_users,
                new_users=new_users,
                paid_users_total=paid_users_total,
                current_paid_users=current_paid_users,
                current_trial_users=current_trial_users,
                inactive_paid_users=inactive_paid_users,
                inactive_free_users=inactive_free_users,
                trial_used_total=trial_used_total,
                completed_transactions_total=completed_transactions_total,
                completed_transactions_period=completed_transactions_period,
                revenue_period=revenue_period,
                total_servers=total_servers,
                online_servers=online_servers,
                total_capacity=total_capacity,
                total_connected=total_connected,
                total_referrals=total_referrals,
                referrals_period=referrals_period,
            )

        if session:
            return await _get_overview(session)

        async with self.session_factory() as session:
            return await _get_overview(session)
