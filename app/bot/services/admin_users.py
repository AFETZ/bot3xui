from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import exists, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.bot.models import (
    AdminUserDetails,
    AdminUserEditorOverview,
    AdminUserListItem,
    AdminUserListPage,
    SubscriptionData,
)
from app.bot.services.payment_stats import PaymentStatsService
from app.bot.services.subscription import SubscriptionService
from app.bot.utils.constants import TransactionStatus
from app.bot.utils.formatting import format_subscription_period
from app.db.models import Promocode, PromocodeActivation, Referral, Transaction, User

logger = logging.getLogger(__name__)


class AdminUserService:
    def __init__(
        self,
        session_factory: async_sessionmaker,
        subscription_service: SubscriptionService,
        payment_stats_service: PaymentStatsService,
    ) -> None:
        self.session_factory = session_factory
        self.subscription = subscription_service
        self.payment_stats = payment_stats_service
        logger.debug("AdminUserService initialized")

    @staticmethod
    def _paid_exists_expression():
        return exists(
            select(Transaction.id).where(
                Transaction.tg_id == User.tg_id,
                Transaction.status == TransactionStatus.COMPLETED,
            )
        )

    @classmethod
    def _apply_filter(cls, query, filter_type: str):
        paid_exists = cls._paid_exists_expression()

        if filter_type == "paid":
            return query.where(paid_exists)
        if filter_type == "trial":
            return query.where(User.current_plan_code.isnot(None), not_(paid_exists))
        if filter_type == "inactive":
            return query.where(User.current_plan_code.is_(None), not_(paid_exists))

        return query

    @staticmethod
    def paginate_items(
        items: list[AdminUserListItem],
        *,
        filter_type: str,
        page: int,
        limit: int,
    ) -> AdminUserListPage:
        total = len(items)
        if total <= 0:
            return AdminUserListPage(
                filter_type=filter_type,  # type: ignore[arg-type]
                page=0,
                limit=limit,
                total=0,
                items=[],
            )

        max_page = max((total - 1) // limit, 0)
        safe_page = min(max(page, 0), max_page)
        start_idx = safe_page * limit
        end_idx = start_idx + limit
        return AdminUserListPage(
            filter_type=filter_type,  # type: ignore[arg-type]
            page=safe_page,
            limit=limit,
            total=total,
            items=items[start_idx:end_idx],
        )

    async def get_editor_overview(
        self,
        session: Optional[AsyncSession] = None,
    ) -> AdminUserEditorOverview:
        async def _get_overview(s: AsyncSession) -> AdminUserEditorOverview:
            seven_days_ago = datetime.utcnow() - timedelta(days=7)
            paid_exists = self._paid_exists_expression()

            total_users = (await s.execute(select(func.count(User.id)))).scalar() or 0
            paid_users = (await s.execute(select(func.count(User.id)).where(paid_exists))).scalar() or 0
            trial_users = (
                await s.execute(
                    select(func.count(User.id)).where(User.current_plan_code.isnot(None), not_(paid_exists))
                )
            ).scalar() or 0
            inactive_users = (
                await s.execute(
                    select(func.count(User.id)).where(User.current_plan_code.is_(None), not_(paid_exists))
                )
            ).scalar() or 0
            new_users_7d = (
                await s.execute(select(func.count(User.id)).where(User.created_at >= seven_days_ago))
            ).scalar() or 0

            return AdminUserEditorOverview(
                total_users=total_users,
                paid_users=paid_users,
                trial_users=trial_users,
                inactive_users=inactive_users,
                new_users_7d=new_users_7d,
            )

        if session:
            return await _get_overview(session)

        async with self.session_factory() as session:
            return await _get_overview(session)

    async def get_user_page(
        self,
        *,
        filter_type: str,
        page: int,
        limit: int,
        session: Optional[AsyncSession] = None,
    ) -> AdminUserListPage:
        async def _get_page(s: AsyncSession) -> AdminUserListPage:
            paid_exists = self._paid_exists_expression().label("has_paid")

            total_query = self._apply_filter(select(func.count(User.id)), filter_type)
            total = (await s.execute(total_query)).scalar() or 0
            if total <= 0:
                return AdminUserListPage(
                    filter_type=filter_type,  # type: ignore[arg-type]
                    page=0,
                    limit=limit,
                    total=0,
                    items=[],
                )

            max_page = max((total - 1) // limit, 0)
            safe_page = min(max(page, 0), max_page)

            query = select(User, paid_exists).options(selectinload(User.server))
            query = self._apply_filter(query, filter_type)
            query = query.order_by(User.created_at.desc()).offset(safe_page * limit).limit(limit)
            rows = (await s.execute(query)).all()

            items = [
                AdminUserListItem(
                    tg_id=user.tg_id,
                    first_name=user.first_name,
                    username=user.username,
                    current_plan_code=user.current_plan_code,
                    has_paid=bool(has_paid),
                    created_at=user.created_at,
                )
                for user, has_paid in rows
            ]

            return AdminUserListPage(
                filter_type=filter_type,  # type: ignore[arg-type]
                page=safe_page,
                limit=limit,
                total=total,
                items=items,
            )

        if session:
            return await _get_page(session)

        async with self.session_factory() as session:
            return await _get_page(session)

    async def search_users(
        self,
        *,
        query_text: str,
        session: Optional[AsyncSession] = None,
        limit: int = 50,
    ) -> list[AdminUserListItem]:
        async def _search(s: AsyncSession) -> list[AdminUserListItem]:
            normalized_query = query_text.strip().removeprefix("@")
            paid_exists = self._paid_exists_expression().label("has_paid")

            query = select(User, paid_exists).options(selectinload(User.server))
            if normalized_query.isdigit():
                query = query.where(User.tg_id == int(normalized_query))
            else:
                pattern = f"%{normalized_query}%"
                query = query.where(
                    or_(
                        User.username.ilike(pattern),
                        User.first_name.ilike(pattern),
                        User.vpn_id.ilike(pattern),
                    )
                )

            query = query.order_by(User.created_at.desc()).limit(limit)
            rows = (await s.execute(query)).all()
            return [
                AdminUserListItem(
                    tg_id=user.tg_id,
                    first_name=user.first_name,
                    username=user.username,
                    current_plan_code=user.current_plan_code,
                    has_paid=bool(has_paid),
                    created_at=user.created_at,
                )
                for user, has_paid in rows
            ]

        if session:
            return await _search(session)

        async with self.session_factory() as session:
            return await _search(session)

    async def get_user_details(
        self,
        *,
        tg_id: int,
        session: Optional[AsyncSession] = None,
        payment_method_currencies: Optional[dict[str, str]] = None,
    ) -> AdminUserDetails | None:
        async def _get_details(s: AsyncSession) -> AdminUserDetails | None:
            target = await User.get(s, tg_id)
            if not target:
                return None

            status = await self.subscription.get_subscription_status(target)
            transactions = await Transaction.get_by_user(session=s, tg_id=target.tg_id)
            completed_transactions = sorted(
                [tx for tx in transactions if tx.status == TransactionStatus.COMPLETED],
                key=lambda tx: tx.created_at,
            )

            revenue_by_currency = await self.payment_stats.get_user_payment_stats(
                user_id=target.tg_id,
                session=s,
                payment_method_currencies=payment_method_currencies,
            )

            referral_count = await Referral.get_referral_count(s, target.tg_id)
            referral_record = await Referral.get_referral(s, target.tg_id)
            multi_use_promocodes = (
                await s.execute(
                    select(Promocode)
                    .join(PromocodeActivation, PromocodeActivation.promocode_id == Promocode.id)
                    .where(PromocodeActivation.user_tg_id == target.tg_id)
                    .order_by(PromocodeActivation.activated_at.desc())
                )
            ).scalars().all()
            all_promocodes = list(target.activated_promocodes or []) + list(multi_use_promocodes)

            return AdminUserDetails(
                tg_id=target.tg_id,
                first_name=target.first_name,
                username=target.username,
                vpn_id=target.vpn_id,
                created_at=target.created_at,
                language_code=target.language_code,
                server_name=target.server.name if target.server else None,
                server_host=target.server.host if target.server else None,
                server_online=target.server.online if target.server else None,
                subscription_status_ok=status.status_check_ok,
                subscription_active=status.is_active,
                subscription_plan_code=(
                    status.plan.code if status.plan else (target.current_plan_code or None)
                ),
                pending_plan_code=target.pending_plan_code,
                pending_period_duration_days=target.pending_period_duration_days,
                pending_plan_starts_at=target.pending_plan_starts_at,
                expiry_timestamp=status.expiry_timestamp,
                traffic_used=status.client_data.traffic_used if status.client_data else None,
                devices=status.client_data.max_devices if status.client_data else None,
                total_transactions=len(transactions),
                completed_transactions=len(completed_transactions),
                first_payment_at=(
                    completed_transactions[0].created_at if completed_transactions else None
                ),
                last_payment_at=(
                    completed_transactions[-1].created_at if completed_transactions else None
                ),
                revenue_by_currency=revenue_by_currency,
                referral_count=referral_count,
                referrer_tg_id=referral_record.referrer_tg_id if referral_record else None,
                trial_used=target.is_trial_used,
                source_invite_name=target.source_invite_name,
                is_blocked=target.is_blocked,
                personal_discount_percent=target.personal_discount_percent,
                activated_promocodes=[
                    f"{promocode.code} · {format_subscription_period(promocode.duration)}"
                    for promocode in all_promocodes[:8]
                ],
                latest_transactions=[
                    self._format_transaction_for_admin(transaction)
                    for transaction in sorted(
                        transactions,
                        key=lambda transaction: transaction.created_at,
                        reverse=True,
                    )[:8]
                ],
            )

        if session:
            return await _get_details(session)

        async with self.session_factory() as session:
            return await _get_details(session)

    @staticmethod
    def _format_transaction_for_admin(transaction: Transaction) -> str:
        try:
            data = SubscriptionData.unpack(transaction.subscription)
            plan = data.plan_code or f"{data.devices} devices"
            duration = format_subscription_period(data.duration)
            price = data.price
        except Exception:
            plan = "?"
            duration = "?"
            price = "?"

        created_at = transaction.created_at.strftime("%Y-%m-%d")
        return (
            f"{created_at} · {transaction.status.value} · {plan} · "
            f"{duration} · {price} · {transaction.payment_id}"
        )
