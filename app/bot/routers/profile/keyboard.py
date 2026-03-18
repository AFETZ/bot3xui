from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.i18n import gettext as _
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.routers.misc.keyboard import back_to_main_menu_button
from app.bot.utils.navigation import NavDownload, NavProfile, NavSubscription


def buy_subscription_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text=_("profile:button:buy_subscription"),
            callback_data=NavSubscription.MAIN,
        )
    )

    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def profile_keyboard(*, show_additional_profile_key: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text=_("profile:button:show_key"),
            callback_data=NavProfile.SHOW_KEY,
        )
    )
    if show_additional_profile_key:
        builder.row(
            InlineKeyboardButton(
                text=_("profile:button:show_additional_key"),
                callback_data=NavProfile.SHOW_ADDITIONAL_KEY,
            )
        )
    builder.row(
        InlineKeyboardButton(
            text=_("profile:button:connect"),
            callback_data=NavDownload.MAIN,
        )
    )

    builder.row(back_to_main_menu_button())
    return builder.as_markup()
