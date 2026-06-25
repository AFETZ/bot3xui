import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.utils.navigation import NavMain
from app.db.models import User

logger = logging.getLogger(__name__)
router = Router(name=__name__)


async def close_callback_message(callback: CallbackQuery, user: User) -> None:
    message: Message | None = callback.message
    if message is None:
        await callback.answer()
        return

    close_targets = (
        ("delete", lambda: message.delete()),
        ("clear_markup", lambda: message.edit_reply_markup(reply_markup=None)),
        ("edit_text", lambda: message.edit_text(text="Закрыто", reply_markup=None)),
    )

    last_exception: Exception | None = None
    for action, operation in close_targets:
        try:
            await operation()
            await callback.answer()
            logger.debug(
                "Closed callback message for user %s via %s.",
                user.tg_id,
                action,
            )
            return
        except Exception as exception:
            last_exception = exception
            logger.debug(
                "Unable to close callback message for user %s via %s: %s",
                user.tg_id,
                action,
                exception,
            )

    await callback.answer()
    if last_exception:
        logger.warning(
            "Unable to close callback message for user %s. Last error: %s",
            user.tg_id,
            last_exception,
        )


@router.callback_query(F.data.startswith(NavMain.CLOSE_NOTIFICATION))
async def callback_close_notification(callback: CallbackQuery, user: User) -> None:
    logger.debug(
        "User %s closed notification: %s",
        user.tg_id,
        getattr(callback.message, "message_id", None),
    )
    await close_callback_message(callback=callback, user=user)


@router.callback_query(F.data.startswith(NavMain.REDIRECT_TO_DOWNLOAD))
async def callback_redirect_to_download(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
) -> None:
    from app.bot.routers.download.handler import callback_download

    logger.debug(
        "User %s redirected to download: %s",
        user.tg_id,
        getattr(callback.message, "message_id", None),
    )
    await callback.answer()
    await callback_download(callback=callback, user=user, state=state)
