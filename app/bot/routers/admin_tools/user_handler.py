import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.models import AdminUserDetails, AdminUserListItem, AdminUserListPage, ServicesContainer
from app.bot.payment_gateways import GatewayFactory
from app.bot.routers.misc.keyboard import back_keyboard
from app.bot.utils.constants import MAIN_MESSAGE_ID_KEY, Currency
from app.bot.utils.formatting import format_remaining_time
from app.bot.utils.navigation import NavAdminTools
from app.db.models import User

from .keyboard import user_details_keyboard, user_editor_keyboard, user_list_keyboard

logger = logging.getLogger(__name__)
router = Router(name=__name__)

USERS_PER_PAGE = 8
USER_RETURN_CONTEXT_KEY = "user_return_context"
USER_SEARCH_QUERY_KEY = "user_search_query"
USER_TARGET_TG_ID_KEY = "target_tg_id"


class UserSearchStates(StatesGroup):
    waiting_search = State()


class UserMessageStates(StatesGroup):
    waiting_message = State()


@router.callback_query(F.data == NavAdminTools.USER_EDITOR, IsAdmin())
async def callback_user_editor(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
    session: AsyncSession,
    services: ServicesContainer,
) -> None:
    logger.info("Admin %s opened user editor.", user.tg_id)
    overview = await services.admin_users.get_editor_overview(session=session)
    await state.set_state(None)
    await state.update_data(
        {
            USER_RETURN_CONTEXT_KEY: {"kind": "editor"},
            USER_SEARCH_QUERY_KEY: None,
        }
    )
    await callback.message.edit_text(
        text=_("user_editor:message:main").format(
            total=overview.total_users,
            paid=overview.paid_users,
            trial=overview.trial_users,
            inactive=overview.inactive_users,
            new_users_7d=overview.new_users_7d,
        ),
        reply_markup=user_editor_keyboard(overview=overview),
    )


@router.callback_query(
    F.data.in_(
        {
            NavAdminTools.USER_LIST,
            NavAdminTools.USER_ACTIVE_FILTER,
            NavAdminTools.USER_PAID_FILTER,
            NavAdminTools.USER_TRIAL_FILTER,
            NavAdminTools.USER_INACTIVE_FILTER,
            NavAdminTools.USER_ALL_FILTER,
        }
    ),
    IsAdmin(),
)
async def callback_user_list(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    logger.info("Admin %s opened user list.", user.tg_id)
    filter_type = _resolve_filter_type(callback.data)
    await _render_filter_page(
        callback_message=callback.message,
        filter_type=filter_type,
        page=0,
        session=session,
        state=state,
        services=services,
    )


@router.callback_query(F.data.startswith(NavAdminTools.USER_LIST_PAGE), IsAdmin())
async def callback_user_list_page(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    parts = callback.data.split("_")
    page = int(parts[-1])
    filter_type = parts[-2] if len(parts) > 3 else "all"
    logger.info(
        "Admin %s opened user list page %s for filter %s.",
        user.tg_id,
        page,
        filter_type,
    )

    if filter_type == "search":
        await _render_search_results_page(
            callback_message=callback.message,
            page=page,
            session=session,
            state=state,
            services=services,
        )
        return

    await _render_filter_page(
        callback_message=callback.message,
        filter_type=filter_type,
        page=page,
        session=session,
        state=state,
        services=services,
    )


@router.callback_query(F.data == NavAdminTools.USER_SEARCH, IsAdmin())
async def callback_user_search(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
) -> None:
    logger.info("Admin %s started user search.", user.tg_id)
    await _render_search_prompt(callback.message, state)


@router.message(UserSearchStates.waiting_search, IsAdmin())
async def handle_user_search(
    message: Message,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
    gateway_factory: GatewayFactory,
) -> None:
    query_text = (message.text or "").strip()
    logger.info("Admin %s searching for: %s", user.tg_id, query_text)

    data = await state.get_data()
    main_message_id = data.get(MAIN_MESSAGE_ID_KEY)
    found_users = await services.admin_users.search_users(
        query_text=query_text,
        session=session,
    )

    if not found_users:
        await services.notification.notify_by_message(
            message=message,
            text=_("user_editor:ntf:not_found"),
            duration=5,
        )
        return

    if len(found_users) == 1:
        await state.set_state(None)
        await state.update_data(
            {
                USER_RETURN_CONTEXT_KEY: {"kind": "search_prompt"},
                USER_SEARCH_QUERY_KEY: query_text,
            }
        )
        await _render_user_details(
            chat_id=message.chat.id,
            message_id=main_message_id,
            tg_id=found_users[0].tg_id,
            session=session,
            services=services,
            gateway_factory=gateway_factory,
            bot=message.bot,
        )
        return

    await state.set_state(None)
    await state.update_data(
        {
            USER_RETURN_CONTEXT_KEY: {"kind": "search_results", "page": 0},
            USER_SEARCH_QUERY_KEY: query_text,
        }
    )

    search_page = services.admin_users.paginate_items(
        found_users,
        filter_type="search",
        page=0,
        limit=USERS_PER_PAGE,
    )
    await message.bot.edit_message_text(
        text=_build_search_results_text(query=query_text, user_page=search_page),
        chat_id=message.chat.id,
        message_id=main_message_id,
        reply_markup=user_list_keyboard(search_page),
    )


@router.callback_query(F.data.startswith(NavAdminTools.USER_DETAILS), IsAdmin())
async def callback_user_details(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
    gateway_factory: GatewayFactory,
) -> None:
    target_tg_id = int(callback.data.split("_")[-1])
    logger.info("Admin %s viewing user %s.", user.tg_id, target_tg_id)
    await state.set_state(None)
    await _render_user_details(
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        tg_id=target_tg_id,
        session=session,
        services=services,
        gateway_factory=gateway_factory,
        bot=callback.bot,
    )


@router.callback_query(F.data == NavAdminTools.USER_BACK, IsAdmin())
async def callback_user_back(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    logger.info("Admin %s navigated back inside user editor.", user.tg_id)
    context = (await state.get_data()).get(USER_RETURN_CONTEXT_KEY) or {"kind": "editor"}
    kind = context.get("kind")

    if kind == "filter":
        await _render_filter_page(
            callback_message=callback.message,
            filter_type=context.get("filter_type", "all"),
            page=context.get("page", 0),
            session=session,
            state=state,
            services=services,
        )
        return

    if kind == "search_results":
        await _render_search_results_page(
            callback_message=callback.message,
            page=context.get("page", 0),
            session=session,
            state=state,
            services=services,
        )
        return

    if kind == "search_prompt":
        await _render_search_prompt(callback.message, state)
        return

    await callback_user_editor(
        callback=callback,
        user=user,
        state=state,
        session=session,
        services=services,
    )


@router.callback_query(F.data.startswith(NavAdminTools.USER_SEND_MESSAGE), IsAdmin())
async def callback_user_send_message(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
) -> None:
    target_tg_id = int(callback.data.split("_")[-1])
    logger.info("Admin %s wants to send message to %s.", user.tg_id, target_tg_id)

    await state.set_state(UserMessageStates.waiting_message)
    await state.update_data(
        {
            MAIN_MESSAGE_ID_KEY: callback.message.message_id,
            USER_TARGET_TG_ID_KEY: target_tg_id,
        }
    )

    await callback.message.edit_text(
        text=_("user_editor:message:enter_message").format(tg_id=target_tg_id),
        reply_markup=back_keyboard(NavAdminTools.USER_DETAILS + f"_{target_tg_id}"),
    )


@router.message(UserMessageStates.waiting_message, IsAdmin())
async def handle_user_send_message(
    message: Message,
    user: User,
    state: FSMContext,
    services: ServicesContainer,
    session: AsyncSession,
    gateway_factory: GatewayFactory,
) -> None:
    data = await state.get_data()
    target_tg_id = data.get(USER_TARGET_TG_ID_KEY)
    main_message_id = data.get(MAIN_MESSAGE_ID_KEY)

    try:
        await message.bot.send_message(chat_id=target_tg_id, text=message.text)
        await state.set_state(None)
        await _render_user_details(
            chat_id=message.chat.id,
            message_id=main_message_id,
            tg_id=target_tg_id,
            session=session,
            services=services,
            gateway_factory=gateway_factory,
            bot=message.bot,
        )
        await services.notification.notify_by_message(
            message=message,
            text=_("user_editor:ntf:message_sent"),
            duration=5,
        )
    except Exception as exception:
        logger.error("Failed to send message to %s: %s", target_tg_id, exception)
        await services.notification.notify_by_message(
            message=message,
            text=_("user_editor:ntf:message_failed"),
            duration=5,
        )


async def _render_filter_page(
    *,
    callback_message,
    filter_type: str,
    page: int,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    user_page = await services.admin_users.get_user_page(
        filter_type=filter_type,
        page=page,
        limit=USERS_PER_PAGE,
        session=session,
    )
    if user_page.total <= 0:
        await state.update_data(
            {
                USER_RETURN_CONTEXT_KEY: {"kind": "editor"},
                USER_SEARCH_QUERY_KEY: None,
            }
        )
        await callback_message.edit_text(
            text=_("user_editor:message:no_users"),
            reply_markup=back_keyboard(NavAdminTools.USER_EDITOR),
        )
        return

    await state.update_data(
        {
            USER_RETURN_CONTEXT_KEY: {
                "kind": "filter",
                "filter_type": user_page.filter_type,
                "page": user_page.page,
            },
            USER_SEARCH_QUERY_KEY: None,
        }
    )
    await callback_message.edit_text(
        text=_build_user_list_text(user_page),
        reply_markup=user_list_keyboard(user_page),
    )


async def _render_search_prompt(callback_message, state: FSMContext) -> None:
    await state.set_state(UserSearchStates.waiting_search)
    await state.update_data(
        {
            MAIN_MESSAGE_ID_KEY: callback_message.message_id,
            USER_RETURN_CONTEXT_KEY: {"kind": "search_prompt"},
        }
    )
    await callback_message.edit_text(
        text=_("user_editor:message:search"),
        reply_markup=back_keyboard(NavAdminTools.USER_EDITOR),
    )


async def _render_search_results_page(
    *,
    callback_message,
    page: int,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    data = await state.get_data()
    query_text = data.get(USER_SEARCH_QUERY_KEY)
    if not query_text:
        await _render_search_prompt(callback_message, state)
        return

    found_users = await services.admin_users.search_users(
        query_text=query_text,
        session=session,
    )
    if not found_users:
        await _render_search_prompt(callback_message, state)
        return

    search_page = services.admin_users.paginate_items(
        found_users,
        filter_type="search",
        page=page,
        limit=USERS_PER_PAGE,
    )
    await state.update_data(
        {
            USER_RETURN_CONTEXT_KEY: {
                "kind": "search_results",
                "page": search_page.page,
            }
        }
    )
    await callback_message.edit_text(
        text=_build_search_results_text(query=query_text, user_page=search_page),
        reply_markup=user_list_keyboard(search_page),
    )


async def _render_user_details(
    *,
    chat_id: int,
    message_id: int,
    tg_id: int,
    session: AsyncSession,
    services: ServicesContainer,
    gateway_factory: GatewayFactory,
    bot,
) -> None:
    details = await services.admin_users.get_user_details(
        tg_id=tg_id,
        session=session,
        payment_method_currencies=_get_payment_method_currencies(gateway_factory),
    )
    if not details:
        await bot.edit_message_text(
            text=_("user_editor:message:no_users"),
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=back_keyboard(NavAdminTools.USER_EDITOR),
        )
        return

    await bot.edit_message_text(
        text=_build_user_details_text(details),
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=user_details_keyboard(details.tg_id),
    )


def _build_user_list_text(user_page: AdminUserListPage) -> str:
    return _("user_editor:message:list").format(
        total=user_page.total,
        filter=_get_filter_label(user_page.filter_type),
        page=user_page.page + 1,
        pages=user_page.pages,
    )


def _build_search_results_text(*, query: str, user_page: AdminUserListPage) -> str:
    return _("user_editor:message:search_results").format(
        total=user_page.total,
        query=query,
        page=user_page.page + 1,
        pages=user_page.pages,
    )


def _build_user_details_text(details: AdminUserDetails) -> str:
    username_display = f"@{details.username}" if details.username else "—"
    tg_link = f"tg://user?id={details.tg_id}"

    if details.subscription_active and details.expiry_timestamp not in (None, -1):
        sub_status = _("user_editor:detail:active_subscription").format(
            plan=details.subscription_plan_code or "?",
            days_left=format_remaining_time(details.expiry_timestamp),
        )
    elif details.subscription_active:
        sub_status = _("user_editor:detail:active_subscription").format(
            plan=details.subscription_plan_code or "?",
            days_left="∞",
        )
    elif not details.subscription_status_ok:
        sub_status = _("user_editor:detail:panel_unavailable")
    elif details.subscription_plan_code:
        sub_status = _("user_editor:detail:expired_subscription").format(
            plan=details.subscription_plan_code,
        )
    else:
        sub_status = _("user_editor:detail:no_subscription")

    revenue_text = _format_revenue(details.revenue_by_currency)
    referral_info = (
        _("user_editor:detail:referred_by").format(referrer_tg_id=details.referrer_tg_id)
        if details.referrer_tg_id
        else _("user_editor:detail:no_referrer")
    )

    return _("user_editor:message:details").format(
        first_name=details.first_name,
        tg_id=details.tg_id,
        tg_link=tg_link,
        username=username_display,
        vpn_id=details.vpn_id,
        created_at=details.created_at.strftime("%Y-%m-%d %H:%M"),
        language=details.language_code,
        server=details.server_name or "—",
        subscription=sub_status,
        devices=details.devices or "—",
        traffic_used=details.traffic_used or "—",
        total_transactions=details.total_transactions,
        completed_transactions=details.completed_transactions,
        first_payment_at=_format_datetime(details.first_payment_at),
        last_payment_at=_format_datetime(details.last_payment_at),
        revenue_text=revenue_text,
        referrals_count=details.referral_count,
        referral_info=referral_info,
        trial_used="+" if details.trial_used else "—",
        source_invite=details.source_invite_name or "—",
    )


def _resolve_filter_type(callback_data: str) -> str:
    if callback_data in (NavAdminTools.USER_ACTIVE_FILTER, NavAdminTools.USER_PAID_FILTER):
        return "paid"
    if callback_data == NavAdminTools.USER_TRIAL_FILTER:
        return "trial"
    if callback_data == NavAdminTools.USER_INACTIVE_FILTER:
        return "inactive"
    return "all"


def _get_filter_label(filter_type: str) -> str:
    if filter_type in ("paid", "active"):
        return _("user_editor:filter:paid")
    if filter_type == "trial":
        return _("user_editor:filter:trial")
    if filter_type == "inactive":
        return _("user_editor:filter:inactive")
    return _("user_editor:filter:all")


def _format_datetime(value) -> str:
    if value is None:
        return "—"
    return value.strftime("%Y-%m-%d %H:%M")


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


def _get_payment_method_currencies(gateway_factory: GatewayFactory) -> dict[str, str]:
    return {gateway.callback: gateway.currency.code for gateway in gateway_factory.get_gateways()}
