import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.models import AdminStatisticsOverview, ServicesContainer
from app.bot.payment_gateways import GatewayFactory
from app.bot.utils.constants import Currency
from app.bot.utils.navigation import NavAdminTools
from app.db.models import User

from .keyboard import statistics_keyboard

DEFAULT_PERIOD_CODE = "7d"

logger = logging.getLogger(__name__)
router = Router(name=__name__)


@router.callback_query(F.data == NavAdminTools.STATISTICS, IsAdmin())
async def callback_statistics(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
    gateway_factory: GatewayFactory,
) -> None:
    logger.info("Admin %s opened statistics.", user.tg_id)
    await _render_statistics(
        callback=callback,
        session=session,
        services=services,
        gateway_factory=gateway_factory,
        period_code=DEFAULT_PERIOD_CODE,
    )


@router.callback_query(F.data.startswith(NavAdminTools.STATISTICS_PERIOD), IsAdmin())
async def callback_statistics_period(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
    gateway_factory: GatewayFactory,
) -> None:
    period_code = callback.data.removeprefix(f"{NavAdminTools.STATISTICS_PERIOD.value}_")
    logger.info("Admin %s switched statistics period to %s.", user.tg_id, period_code)
    await _render_statistics(
        callback=callback,
        session=session,
        services=services,
        gateway_factory=gateway_factory,
        period_code=period_code,
    )


async def _render_statistics(
    *,
    callback: CallbackQuery,
    session: AsyncSession,
    services: ServicesContainer,
    gateway_factory: GatewayFactory,
    period_code: str,
) -> None:
    payment_method_currencies = {
        gateway.callback: gateway.currency.code for gateway in gateway_factory.get_gateways()
    }
    overview = await services.admin_statistics.get_overview(
        period_code=period_code,
        session=session,
        payment_method_currencies=payment_method_currencies,
    )

    await callback.message.edit_text(
        text=_build_statistics_text(overview),
        reply_markup=statistics_keyboard(period_code=period_code),
    )


def _build_statistics_text(overview: AdminStatisticsOverview) -> str:
    return _("statistics:message:main").format(
        period_label=_get_period_label(overview.period_code),
        generated_at=overview.generated_at.strftime("%Y-%m-%d %H:%M UTC"),
        total_users=overview.total_users,
        new_users=overview.new_users,
        paid_users_total=overview.paid_users_total,
        current_paid_users=overview.current_paid_users,
        current_trial_users=overview.current_trial_users,
        inactive_paid_users=overview.inactive_paid_users,
        inactive_free_users=overview.inactive_free_users,
        trial_used_total=overview.trial_used_total,
        completed_transactions_total=overview.completed_transactions_total,
        completed_transactions_period=overview.completed_transactions_period,
        revenue_text=_format_revenue(overview.revenue_period),
        total_servers=overview.total_servers,
        online_servers=overview.online_servers,
        total_capacity=overview.total_capacity,
        total_connected=overview.total_connected,
        server_load_percent=overview.server_load_percent,
        total_referrals=overview.total_referrals,
        referrals_period=overview.referrals_period,
    )


def _get_period_label(period_code: str) -> str:
    labels = {
        "today": _("statistics:period:today"),
        "7d": _("statistics:period:7d"),
        "30d": _("statistics:period:30d"),
        "all": _("statistics:period:all"),
    }
    return labels.get(period_code, _("statistics:period:7d"))


def _format_revenue(revenue_by_currency: dict[str, float]) -> str:
    if not revenue_by_currency:
        return "• " + _("statistics:revenue:none")

    lines: list[str] = []
    for currency_code, amount in revenue_by_currency.items():
        try:
            currency_symbol = Currency.from_code(currency_code).symbol
        except ValueError:
            currency_symbol = currency_code
        lines.append(f"• {amount:.2f} {currency_symbol}")
    return "\n".join(lines)
