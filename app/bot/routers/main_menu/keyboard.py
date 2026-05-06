from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.i18n import gettext as _
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.utils.navigation import (
    NavAdminTools,
    NavProfile,
    NavReferral,
    NavSubscription,
    NavSupport,
)

MENU_BUTTON_TEXT = "📋 Меню"


def menu_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=MENU_BUTTON_TEXT)]],
        resize_keyboard=True,
        is_persistent=True,
    )


def main_menu_keyboard(
    is_admin: bool = False,
    is_referral_available: bool = False,
    is_trial_available: bool = False,
    is_referred_trial_available: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if is_referred_trial_available:
        builder.row(
            InlineKeyboardButton(
                text=_("referral:button:get_referred_trial"),
                callback_data=NavReferral.GET_REFERRED_TRIAL,
            )
        )
    elif is_trial_available:
        builder.row(
            InlineKeyboardButton(
                text=_("subscription:button:get_trial"), callback_data=NavSubscription.GET_TRIAL
            )
        )

    builder.row(
        InlineKeyboardButton(
            text=_("main_menu:button:profile"),
            callback_data=NavProfile.MAIN,
        ),
        InlineKeyboardButton(
            text=_("main_menu:button:subscription"),
            callback_data=NavSubscription.MAIN,
        ),
    )
    builder.row(
        *(
            [
                InlineKeyboardButton(
                    text=_("main_menu:button:referral"),
                    callback_data=NavReferral.MAIN,
                )
            ]
            if is_referral_available
            else []
        ),
        InlineKeyboardButton(
            text=_("main_menu:button:support"),
            callback_data=NavSupport.MAIN,
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text=_("main_menu:button:news_channel"),
            url="https://t.me/AFetZEA",
        )
    )

    if is_admin:
        builder.row(
            InlineKeyboardButton(
                text=_("main_menu:button:admin_tools"),
                callback_data=NavAdminTools.MAIN,
            )
        )

    return builder.as_markup()
