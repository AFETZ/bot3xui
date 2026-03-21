import logging
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.i18n import gettext as _
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.bot.filters import IsAdmin
from app.bot.models import ServicesContainer
from app.bot.routers.misc.keyboard import back_keyboard
from app.bot.utils.constants import MAIN_MESSAGE_ID_KEY, TransactionStatus
from app.bot.utils.navigation import NavAdminTools
from app.db.models import Referral, Server, Transaction, User

from .keyboard import (
    user_details_keyboard,
    user_editor_keyboard,
    user_list_keyboard,
)

logger = logging.getLogger(__name__)
router = Router(name=__name__)

USERS_PER_PAGE = 8


class UserSearchStates(StatesGroup):
    waiting_search = State()


class UserMessageStates(StatesGroup):
    waiting_message = State()


@router.callback_query(F.data == NavAdminTools.USER_EDITOR, IsAdmin())
async def callback_user_editor(
    callback: CallbackQuery, user: User, state: FSMContext
) -> None:
    logger.info(f"Admin {user.tg_id} opened user editor.")
    await state.set_state(None)
    await callback.message.edit_text(
        text=_("user_editor:message:main"),
        reply_markup=user_editor_keyboard(),
    )


@router.callback_query(
    F.data.in_({
        NavAdminTools.USER_LIST,
        NavAdminTools.USER_ACTIVE_FILTER,
        NavAdminTools.USER_INACTIVE_FILTER,
        NavAdminTools.USER_ALL_FILTER,
    }),
    IsAdmin(),
)
async def callback_user_list(
    callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext
) -> None:
    logger.info(f"Admin {user.tg_id} opened user list.")
    await state.set_state(None)

    filter_type = "all"
    if callback.data == NavAdminTools.USER_ACTIVE_FILTER:
        filter_type = "active"
    elif callback.data == NavAdminTools.USER_INACTIVE_FILTER:
        filter_type = "inactive"

    users = await _get_filtered_users(session, filter_type)

    if not users:
        await callback.message.edit_text(
            text=_("user_editor:message:no_users"),
            reply_markup=back_keyboard(NavAdminTools.USER_EDITOR),
        )
        return

    total = len(users)
    text = _("user_editor:message:list").format(total=total, filter=_get_filter_label(filter_type))
    await callback.message.edit_text(
        text=text,
        reply_markup=user_list_keyboard(users, page=0, filter_type=filter_type),
    )


@router.callback_query(F.data.startswith(NavAdminTools.USER_LIST_PAGE), IsAdmin())
async def callback_user_list_page(
    callback: CallbackQuery, user: User, session: AsyncSession
) -> None:
    parts = callback.data.split("_")
    page = int(parts[-1])
    filter_type = parts[-2] if len(parts) > 3 else "all"

    users = await _get_filtered_users(session, filter_type)
    total = len(users)
    text = _("user_editor:message:list").format(total=total, filter=_get_filter_label(filter_type))

    await callback.message.edit_text(
        text=text,
        reply_markup=user_list_keyboard(users, page=page, filter_type=filter_type),
    )


@router.callback_query(F.data == NavAdminTools.USER_SEARCH, IsAdmin())
async def callback_user_search(
    callback: CallbackQuery, user: User, state: FSMContext
) -> None:
    logger.info(f"Admin {user.tg_id} started user search.")
    await state.set_state(UserSearchStates.waiting_search)
    await state.update_data({MAIN_MESSAGE_ID_KEY: callback.message.message_id})

    await callback.message.edit_text(
        text=_("user_editor:message:search"),
        reply_markup=back_keyboard(NavAdminTools.USER_EDITOR),
    )


@router.message(UserSearchStates.waiting_search, IsAdmin())
async def handle_user_search(
    message: Message,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    query_text = message.text.strip()
    logger.info(f"Admin {user.tg_id} searching for: {query_text}")

    data = await state.get_data()
    main_message_id = data.get(MAIN_MESSAGE_ID_KEY)

    found_users = await _search_users(session, query_text)

    if not found_users:
        await services.notification.notify_by_message(
            message=message,
            text=_("user_editor:ntf:not_found"),
            duration=5,
        )
        return

    if len(found_users) == 1:
        await state.set_state(None)
        target = found_users[0]
        text = await _build_user_details_text(session, target)
        await message.bot.edit_message_text(
            text=text,
            chat_id=message.chat.id,
            message_id=main_message_id,
            reply_markup=user_details_keyboard(target.tg_id),
        )
    else:
        await state.set_state(None)
        total = len(found_users)
        text = _("user_editor:message:search_results").format(total=total, query=query_text)
        await message.bot.edit_message_text(
            text=text,
            chat_id=message.chat.id,
            message_id=main_message_id,
            reply_markup=user_list_keyboard(found_users, page=0, filter_type="all"),
        )


@router.callback_query(F.data.startswith(NavAdminTools.USER_DETAILS), IsAdmin())
async def callback_user_details(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    parts = callback.data.split("_")
    target_tg_id = int(parts[-1])
    logger.info(f"Admin {user.tg_id} viewing user {target_tg_id}.")
    await state.set_state(None)

    target = await User.get(session, target_tg_id)
    if not target:
        await callback.answer(text=_("user_editor:popup:user_not_found"), show_alert=True)
        return

    text = await _build_user_details_text(session, target)
    await callback.message.edit_text(
        text=text,
        reply_markup=user_details_keyboard(target.tg_id),
    )


@router.callback_query(F.data.startswith(NavAdminTools.USER_SEND_MESSAGE), IsAdmin())
async def callback_user_send_message(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
) -> None:
    parts = callback.data.split("_")
    target_tg_id = int(parts[-1])
    logger.info(f"Admin {user.tg_id} wants to send message to {target_tg_id}.")

    await state.set_state(UserMessageStates.waiting_message)
    await state.update_data({
        MAIN_MESSAGE_ID_KEY: callback.message.message_id,
        "target_tg_id": target_tg_id,
    })

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
) -> None:
    data = await state.get_data()
    target_tg_id = data.get("target_tg_id")
    main_message_id = data.get(MAIN_MESSAGE_ID_KEY)

    try:
        await message.bot.send_message(
            chat_id=target_tg_id,
            text=message.text,
        )

        await state.set_state(None)
        target = await User.get(session, target_tg_id)
        text = await _build_user_details_text(session, target)

        await message.bot.edit_message_text(
            text=text,
            chat_id=message.chat.id,
            message_id=main_message_id,
            reply_markup=user_details_keyboard(target_tg_id),
        )

        await services.notification.notify_by_message(
            message=message,
            text=_("user_editor:ntf:message_sent"),
            duration=5,
        )
    except Exception as e:
        logger.error(f"Failed to send message to {target_tg_id}: {e}")
        await services.notification.notify_by_message(
            message=message,
            text=_("user_editor:ntf:message_failed"),
            duration=5,
        )


async def _get_filtered_users(session: AsyncSession, filter_type: str) -> list[User]:
    query = select(User).options(selectinload(User.server))

    if filter_type == "active":
        now = datetime.now(timezone.utc)
        query = query.where(
            User.current_plan_code.isnot(None),
            User.current_period_started_at.isnot(None),
            User.current_period_duration_days.isnot(None),
        )
    elif filter_type == "inactive":
        query = query.where(
            User.current_plan_code.is_(None),
        )

    query = query.order_by(User.created_at.desc())
    result = await session.execute(query)
    users = result.scalars().all()

    if filter_type == "active":
        now = datetime.now(timezone.utc)
        users = [
            u for u in users
            if u.current_period_started_at and u.current_period_duration_days
            and (u.current_period_started_at + timedelta(days=u.current_period_duration_days)) > now
        ]

    return users


async def _search_users(session: AsyncSession, query_text: str) -> list[User]:
    query = select(User).options(selectinload(User.server))

    if query_text.isdigit():
        tg_id = int(query_text)
        query = query.where(User.tg_id == tg_id)
    else:
        pattern = f"%{query_text}%"
        query = query.where(
            (User.username.ilike(pattern)) | (User.first_name.ilike(pattern))
        )

    query = query.order_by(User.created_at.desc()).limit(50)
    result = await session.execute(query)
    return result.scalars().all()


async def _build_user_details_text(session: AsyncSession, target: User) -> str:
    username_display = f"@{target.username}" if target.username else "—"
    tg_link = f"tg://user?id={target.tg_id}"

    sub_status = _("user_editor:detail:no_subscription")
    if target.current_plan_code and target.current_period_started_at and target.current_period_duration_days:
        expiry = target.current_period_started_at + timedelta(days=target.current_period_duration_days)
        now = datetime.now(timezone.utc)
        if expiry > now:
            remaining = expiry - now
            days_left = remaining.days
            sub_status = _("user_editor:detail:active_subscription").format(
                plan=target.current_plan_code,
                days_left=days_left,
            )
        else:
            sub_status = _("user_editor:detail:expired_subscription").format(
                plan=target.current_plan_code,
            )

    server_name = target.server.name if target.server else "—"

    tx_count = len(target.transactions) if target.transactions else 0
    completed_tx = [
        t for t in (target.transactions or [])
        if t.status == TransactionStatus.COMPLETED
    ]

    referral_count = await Referral.get_referral_count(session, target.tg_id)

    referral_info = _("user_editor:detail:no_referrer")
    referral_record = await Referral.get_referral(session, target.tg_id)
    if referral_record:
        referral_info = _("user_editor:detail:referred_by").format(
            referrer_tg_id=referral_record.referrer_tg_id,
        )

    text = _("user_editor:message:details").format(
        first_name=target.first_name,
        tg_id=target.tg_id,
        tg_link=tg_link,
        username=username_display,
        vpn_id=target.vpn_id,
        created_at=target.created_at.strftime("%Y-%m-%d %H:%M"),
        language=target.language_code,
        server=server_name,
        subscription=sub_status,
        total_transactions=tx_count,
        completed_transactions=len(completed_tx),
        referrals_count=referral_count,
        referral_info=referral_info,
        trial_used="+" if target.is_trial_used else "—",
        source_invite=target.source_invite_name or "—",
    )

    return text


def _get_filter_label(filter_type: str) -> str:
    if filter_type == "active":
        return _("user_editor:filter:active")
    elif filter_type == "inactive":
        return _("user_editor:filter:inactive")
    return _("user_editor:filter:all")
