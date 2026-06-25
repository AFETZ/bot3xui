import html
import logging
from datetime import datetime, timezone
from typing import Any

from aiogram import F, Router
from aiogram.types import CallbackQuery
from redis.asyncio.client import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.models import ServicesContainer
from app.bot.services.runtime_metrics import fd_limits, open_fd_count, runtime_metrics
from app.bot.utils.navigation import NavAdminTools
from app.db.models import User

from .keyboard import health_keyboard

logger = logging.getLogger(__name__)
router = Router(name=__name__)


@router.callback_query(F.data == NavAdminTools.HEALTH, IsAdmin())
async def callback_health(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    redis: Redis,
    services: ServicesContainer,
) -> None:
    logger.info("Admin %s opened runtime health.", user.tg_id)
    db_ok, db_error = await _check_db(session)
    redis_ok, redis_error = await _check_redis(redis)
    text = _build_health_text(
        db_ok=db_ok,
        db_error=db_error,
        redis_ok=redis_ok,
        redis_error=redis_error,
        services=services,
    )
    await callback.message.edit_text(text=text, reply_markup=health_keyboard())


@router.callback_query(F.data == NavAdminTools.HEALTH_CHECK_NODES, IsAdmin())
async def callback_health_check_nodes(
    callback: CallbackQuery,
    user: User,
    services: ServicesContainer,
) -> None:
    logger.info("Admin %s started node healthcheck.", user.tg_id)
    results = await services.server_pool.healthcheck_servers()
    if not results:
        text = "<b>Проверка узлов</b>\n\nНет серверов для проверки."
    else:
        lines = ["<b>Проверка узлов</b>", ""]
        for result in sorted(results, key=lambda item: (not item.online, item.server_name)):
            status = "OK" if result.online else "DOWN"
            latency = f"{result.latency_ms} ms" if result.latency_ms is not None else "n/a"
            lines.append(f"{html.escape(result.server_name)}: {status}, {latency}")
        text = "\n".join(lines)

    await callback.message.edit_text(text=text, reply_markup=health_keyboard())
    await callback.answer()


async def _check_db(session: AsyncSession) -> tuple[bool, str | None]:
    try:
        await session.execute(select(1))
    except Exception as exception:
        return False, str(exception)
    return True, None


async def _check_redis(redis: Redis) -> tuple[bool, str | None]:
    try:
        await redis.ping()
    except Exception as exception:
        return False, str(exception)
    return True, None


def _format_status(ok: bool, error: str | None = None) -> str:
    if ok:
        return "OK"
    return "ERROR" + (f": {html.escape(error)}" if error else "")


def _format_datetime(value: Any) -> str:
    if not value:
        return "-"
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return html.escape(str(value))


def _format_event(event: dict[str, Any] | None) -> str:
    if not event:
        return "-"

    at = _format_datetime(event.get("at"))
    values = [
        f"{key}={html.escape(str(value))}"
        for key, value in event.items()
        if key != "at"
    ]
    suffix = ", ".join(values)
    return f"{at}" + (f" ({suffix})" if suffix else "")


def _format_xui_health(services: ServicesContainer) -> str:
    states = services.vpn.xui_gateway.get_health_snapshot()
    if not states:
        return "нет обращений к 3x-ui после старта"

    lines: list[str] = []
    for state in states:
        marker = "OPEN" if state["circuit_open"] else "OK"
        last_failure = state.get("last_failure") or "-"
        lines.append(
            f"{html.escape(state['server_name'])}: {marker}, "
            f"failures={state['failure_count']}, "
            f"last_success={_format_datetime(state.get('last_success_at'))}, "
            f"last_error={html.escape(str(last_failure))}"
        )
    return "\n".join(lines)


def _build_health_text(
    *,
    db_ok: bool,
    db_error: str | None,
    redis_ok: bool,
    redis_error: str | None,
    services: ServicesContainer,
) -> str:
    snapshot = runtime_metrics.snapshot()
    soft_limit, hard_limit = fd_limits()
    events = snapshot["events"]
    counters = snapshot["counters"]

    return "\n".join(
        [
            "<b>Состояние бота</b>",
            f"Процесс запущен: {_format_datetime(snapshot['started_at'])}",
            f"БД: {_format_status(db_ok, db_error)}",
            f"Redis: {_format_status(redis_ok, redis_error)}",
            f"FD: {open_fd_count() or 'unknown'} / soft={soft_limit}, hard={hard_limit}",
            "",
            "<b>Фоновые задачи</b>",
            f"Expiry: {_format_event(events.get('subscription_expiry.last_run'))}",
            f"Sync: {_format_event(events.get('subscription_sync.last_run'))}",
            f"Payments reconcile: {_format_event(events.get('transactions.reconcile.last_run'))}",
            f"Expired payments: {_format_event(events.get('transactions.cancel_expired.last_run'))}",
            f"Referral rewards: {_format_event(events.get('referrals.rewards.last_run'))}",
            "",
            "<b>3x-ui</b>",
            _format_xui_health(services),
            "",
            "<b>Счетчики</b>",
            f"xui ok={counters.get('xui.calls_ok', 0)}, failed={counters.get('xui.calls_failed', 0)}, rejected={counters.get('xui.circuit_rejected', 0)}",
            f"payments processed={counters.get('payments.success_processed', 0)}, duplicate_locked={counters.get('payments.success_duplicate_locked', 0)}",
        ]
    )
