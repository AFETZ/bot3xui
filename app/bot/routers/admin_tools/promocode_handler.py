import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.models import ServicesContainer
from app.bot.routers.misc.keyboard import back_keyboard
from app.bot.utils.constants import INPUT_PROMOCODE_KEY, MAIN_MESSAGE_ID_KEY
from app.bot.utils.formatting import format_subscription_period
from app.bot.utils.navigation import NavAdminTools
from app.db.models import Promocode, User

from .keyboard import (
    PROMOCODE_CUSTOM_ACTIVATIONS_CALLBACK,
    PROMOCODE_CUSTOM_DURATION_CALLBACK,
    promocode_activations_keyboard,
    promocode_duration_keyboard,
    promocode_editor_keyboard,
)

logger = logging.getLogger(__name__)
router = Router(name=__name__)
PROMOCODE_MIN_DAYS = 1
PROMOCODE_MAX_DAYS = 3650
PROMOCODE_DURATION_KEY = "promocode_duration"
PROMOCODE_MAX_ACTIVATIONS_MIN = 1
PROMOCODE_MAX_ACTIVATIONS_MAX = 100000


class CreatePromocodeStates(StatesGroup):
    selecting_duration = State()
    input_duration = State()
    selecting_activations = State()
    input_activations = State()


class DeletePromocodeStates(StatesGroup):
    promocode_input = State()


class EditPromocodeStates(StatesGroup):
    promocode_input = State()
    selecting_duration = State()
    input_duration = State()


def _parse_duration(value: str | None) -> int | None:
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned.isdigit():
        return None

    duration = int(cleaned)
    if PROMOCODE_MIN_DAYS <= duration <= PROMOCODE_MAX_DAYS:
        return duration
    return None


async def show_promocode_editor_main(message: Message, state: FSMContext) -> None:
    await state.set_state(None)
    main_message_id = await state.get_value(MAIN_MESSAGE_ID_KEY)
    await message.bot.edit_message_text(
        text=_("promocode_editor:message:main"),
        chat_id=message.chat.id,
        message_id=main_message_id,
        reply_markup=promocode_editor_keyboard(),
    )


@router.callback_query(F.data == NavAdminTools.PROMOCODE_EDITOR, IsAdmin())
async def callback_promocode_editor(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    logger.info(f"Admin {user.tg_id} opened promocode editor.")
    await show_promocode_editor_main(message=callback.message, state=state)


# region: Create Promocode


async def _show_activations_step(message, state: FSMContext) -> None:
    await state.set_state(CreatePromocodeStates.selecting_activations)
    await message.edit_text(
        text=_("promocode_editor:message:select_activations"),
        reply_markup=promocode_activations_keyboard(),
    )


async def _finalize_create(
    message: Message,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
    max_activations: int,
) -> None:
    duration = await state.get_value(PROMOCODE_DURATION_KEY)
    logger.info(
        f"Admin {user.tg_id} creating promocode: {duration} days, max_activations={max_activations}."
    )
    promocode = await Promocode.create(
        session=session, duration=duration, max_activations=max_activations
    )
    await show_promocode_editor_main(message=message, state=state)

    if promocode:
        if max_activations == 0:
            act_label = "∞"
        else:
            act_label = str(max_activations)
        await services.notification.notify_by_message(
            message=message,
            text=_("promocode_editor:ntf:created_success_multi").format(
                promocode=promocode.code,
                duration=format_subscription_period(promocode.duration),
                max_activations=act_label,
            ),
        )
    else:
        await services.notification.notify_by_message(
            message=message,
            text=_("promocode_editor:ntf:create_failed"),
            duration=5,
        )


@router.callback_query(F.data == NavAdminTools.CREATE_PROMOCODE, IsAdmin())
async def callback_create_promocode(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    logger.info(f"Admin {user.tg_id} started creating promocode.")
    await state.set_state(CreatePromocodeStates.selecting_duration)
    await callback.message.edit_text(
        text=_("promocode_editor:message:create"),
        reply_markup=promocode_duration_keyboard(),
    )


@router.callback_query(
    CreatePromocodeStates.selecting_duration,
    IsAdmin(),
    (F.data == PROMOCODE_CUSTOM_DURATION_CALLBACK) | F.data.regexp(r"^\d+$"),
)
async def callback_create_duration_selected(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    if callback.data == PROMOCODE_CUSTOM_DURATION_CALLBACK:
        logger.info(f"Admin {user.tg_id} switched to manual duration input for promocode creation.")
        await state.set_state(CreatePromocodeStates.input_duration)
        await callback.message.edit_text(
            text=_("promocode_editor:message:enter_duration").format(
                min_days=PROMOCODE_MIN_DAYS,
                max_days=PROMOCODE_MAX_DAYS,
            ),
            reply_markup=back_keyboard(NavAdminTools.CREATE_PROMOCODE),
        )
        return

    duration = _parse_duration(callback.data)
    if duration is None:
        await services.notification.show_popup(
            callback=callback,
            text=_("promocode_editor:ntf:duration_invalid").format(
                min_days=PROMOCODE_MIN_DAYS,
                max_days=PROMOCODE_MAX_DAYS,
            ),
        )
        return

    await state.update_data({PROMOCODE_DURATION_KEY: duration})
    await _show_activations_step(callback.message, state)


@router.message(CreatePromocodeStates.input_duration, IsAdmin())
async def handle_create_duration_input(
    message: Message,
    user: User,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    duration = _parse_duration(message.text)
    if duration is None:
        await services.notification.notify_by_message(
            message=message,
            text=_("promocode_editor:ntf:duration_invalid").format(
                min_days=PROMOCODE_MIN_DAYS,
                max_days=PROMOCODE_MAX_DAYS,
            ),
            duration=5,
        )
        return

    await state.update_data({PROMOCODE_DURATION_KEY: duration})
    main_message_id = await state.get_value(MAIN_MESSAGE_ID_KEY)
    await state.set_state(CreatePromocodeStates.selecting_activations)
    await message.bot.edit_message_text(
        text=_("promocode_editor:message:select_activations"),
        chat_id=message.chat.id,
        message_id=main_message_id,
        reply_markup=promocode_activations_keyboard(),
    )


@router.callback_query(
    CreatePromocodeStates.selecting_activations,
    IsAdmin(),
    (F.data == PROMOCODE_CUSTOM_ACTIVATIONS_CALLBACK) | F.data.regexp(r"^promo_act_\d+$"),
)
async def callback_create_activations_selected(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    if callback.data == PROMOCODE_CUSTOM_ACTIVATIONS_CALLBACK:
        await state.set_state(CreatePromocodeStates.input_activations)
        await callback.message.edit_text(
            text=_("promocode_editor:message:enter_activations").format(
                min_val=PROMOCODE_MAX_ACTIVATIONS_MIN,
                max_val=PROMOCODE_MAX_ACTIVATIONS_MAX,
            ),
            reply_markup=back_keyboard(NavAdminTools.CREATE_PROMOCODE),
        )
        return

    max_activations = int(callback.data.removeprefix("promo_act_"))
    await _finalize_create(callback.message, user, session, state, services, max_activations)


@router.message(CreatePromocodeStates.input_activations, IsAdmin())
async def handle_create_activations_input(
    message: Message,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    text = message.text.strip() if message.text else ""
    if not text.isdigit():
        await services.notification.notify_by_message(
            message=message,
            text=_("promocode_editor:ntf:activations_invalid").format(
                min_val=PROMOCODE_MAX_ACTIVATIONS_MIN,
                max_val=PROMOCODE_MAX_ACTIVATIONS_MAX,
            ),
            duration=5,
        )
        return

    max_activations = int(text)
    if not (PROMOCODE_MAX_ACTIVATIONS_MIN <= max_activations <= PROMOCODE_MAX_ACTIVATIONS_MAX):
        await services.notification.notify_by_message(
            message=message,
            text=_("promocode_editor:ntf:activations_invalid").format(
                min_val=PROMOCODE_MAX_ACTIVATIONS_MIN,
                max_val=PROMOCODE_MAX_ACTIVATIONS_MAX,
            ),
            duration=5,
        )
        return

    await _finalize_create(message, user, session, state, services, max_activations)


# endregion


# region: Delete Promocode
@router.callback_query(F.data == NavAdminTools.DELETE_PROMOCODE, IsAdmin())
async def callback_delete_promocode(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    logger.info(f"Admin {user.tg_id} started deleting promocode.")
    await state.set_state(DeletePromocodeStates.promocode_input)
    await callback.message.edit_text(
        text=_("promocode_editor:message:delete"),
        reply_markup=back_keyboard(NavAdminTools.PROMOCODE_EDITOR),
    )


@router.message(DeletePromocodeStates.promocode_input, IsAdmin())
async def handle_promocode_input(
    message: Message,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    input_promocode = message.text.strip()
    logger.info(f"Admin {user.tg_id} entered promocode: {input_promocode} for deleting.")

    if await Promocode.delete(session=session, code=input_promocode):
        await show_promocode_editor_main(message=message, state=state)
        await services.notification.notify_by_message(
            message=message,
            text=_("promocode_editor:ntf:deleted_success").format(promocode=input_promocode),
            duration=5,
        )
    else:
        await services.notification.notify_by_message(
            message=message,
            text=_("promocode_editor:ntf:delete_failed"),
            duration=5,
        )


# endregion


# region Edit Promocode
@router.callback_query(F.data == NavAdminTools.EDIT_PROMOCODE, IsAdmin())
async def callback_edit_promocode(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    logger.info(f"Admin {user.tg_id} started deleting promocode.")
    await state.set_state(EditPromocodeStates.promocode_input)
    await callback.message.edit_text(
        text=_("promocode_editor:message:edit"),
        reply_markup=back_keyboard(NavAdminTools.PROMOCODE_EDITOR),
    )


@router.message(EditPromocodeStates.promocode_input, IsAdmin())
async def handle_promocode_input(
    message: Message,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    input_promocode = message.text.strip()
    logger.info(f"Admin {user.tg_id} entered promocode: {input_promocode} for editing.")

    promocode = await Promocode.get(session=session, code=input_promocode)
    if promocode and not promocode.is_activated:
        await state.set_state(EditPromocodeStates.selecting_duration)
        await state.update_data({INPUT_PROMOCODE_KEY: input_promocode})
        main_message_id = await state.get_value(MAIN_MESSAGE_ID_KEY)
        await message.bot.edit_message_text(
            text=_("promocode_editor:message:edit_duration").format(
                promocode=promocode.code,
                duration=promocode.duration,
            ),
            chat_id=message.chat.id,
            message_id=main_message_id,
            reply_markup=promocode_duration_keyboard(),
        )
    else:
        await services.notification.notify_by_message(
            message=message,
            text=_("promocode_editor:ntf:edit_failed"),
            duration=5,
        )


@router.callback_query(
    EditPromocodeStates.selecting_duration,
    IsAdmin(),
    (F.data == PROMOCODE_CUSTOM_DURATION_CALLBACK) | F.data.regexp(r"^\d+$"),
)
async def callback_edit_duration_selected(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    if callback.data == PROMOCODE_CUSTOM_DURATION_CALLBACK:
        logger.info(f"Admin {user.tg_id} switched to manual duration input for promocode editing.")
        await state.set_state(EditPromocodeStates.input_duration)
        await callback.message.edit_text(
            text=_("promocode_editor:message:enter_duration").format(
                min_days=PROMOCODE_MIN_DAYS,
                max_days=PROMOCODE_MAX_DAYS,
            ),
            reply_markup=back_keyboard(NavAdminTools.EDIT_PROMOCODE),
        )
        return

    duration = _parse_duration(callback.data)
    if duration is None:
        await services.notification.show_popup(
            callback=callback,
            text=_("promocode_editor:ntf:duration_invalid").format(
                min_days=PROMOCODE_MIN_DAYS,
                max_days=PROMOCODE_MAX_DAYS,
            ),
        )
        return

    logger.info(f"Admin {user.tg_id} selected {duration} days for promocode.")
    input_promocode = await state.get_value(INPUT_PROMOCODE_KEY)
    promocode = await Promocode.update(
        session=session,
        code=input_promocode,
        duration=duration,
    )
    await show_promocode_editor_main(message=callback.message, state=state)
    await services.notification.notify_by_message(
        message=callback.message,
        text=_("promocode_editor:ntf:edited_success").format(
            promocode=promocode.code,
            duration=format_subscription_period(promocode.duration),
        ),
    )


@router.message(EditPromocodeStates.input_duration, IsAdmin())
async def handle_edit_duration_input(
    message: Message,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    duration = _parse_duration(message.text)
    if duration is None:
        await services.notification.notify_by_message(
            message=message,
            text=_("promocode_editor:ntf:duration_invalid").format(
                min_days=PROMOCODE_MIN_DAYS,
                max_days=PROMOCODE_MAX_DAYS,
            ),
            duration=5,
        )
        return

    input_promocode = await state.get_value(INPUT_PROMOCODE_KEY)
    logger.info(
        f"Admin {user.tg_id} entered manual duration {duration} days for promocode {input_promocode}."
    )
    promocode = await Promocode.update(
        session=session,
        code=input_promocode,
        duration=duration,
    )
    await show_promocode_editor_main(message=message, state=state)
    await services.notification.notify_by_message(
        message=message,
        text=_("promocode_editor:ntf:edited_success").format(
            promocode=promocode.code,
            duration=format_subscription_period(promocode.duration),
        ),
    )


# endregion
