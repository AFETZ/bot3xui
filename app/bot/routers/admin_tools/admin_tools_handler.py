import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.i18n import gettext as _
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.filters import IsAdmin, IsDev
from app.bot.models import SubscriptionData
from app.bot.payment_gateways import GatewayFactory
from app.bot.services import ServicesContainer
from app.bot.utils.navigation import NavAdminTools, NavSubscription
from app.db.models import User

from .keyboard import admin_tools_keyboard

logger = logging.getLogger(__name__)
router = Router(name=__name__)


@router.callback_query(F.data == NavAdminTools.MAIN, IsAdmin())
async def callback_admin_tools(callback: CallbackQuery, user: User) -> None:
    logger.info(f"Admin {user.tg_id} opened admin tools.")
    is_dev = await IsDev()(user_id=user.tg_id)
    await callback.message.edit_text(
        text=_("admin_tools:message:main"),
        reply_markup=admin_tools_keyboard(is_dev),
    )


from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Transaction


@router.callback_query(F.data == NavAdminTools.TEST, IsAdmin())
async def callback_admin_tools(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
) -> None:
    logger.info(f"Admin {user.tg_id} clicked TEST BUTTON.")

    text = (
        "<b>bold</b>\n"
        "<i>italic</i>\n"
        "<u>underline</u>\n"
        "<s>strikethrough</s>\n"
        "<tg-spoiler>spoiler</tg-spoiler>\n\n"
        "<a href='http://www.example.com/'>inline URL</a>\n"
        "<a href='tg://user?id=243323533'>inline mention of a user</a>\n"
        "<tg-emoji emoji-id='5389102131527556772'>👍</tg-emoji>\n\n"
        "<code>inline fixed-width code</code>\n"
        "<pre>pre-formatted fixed-width code block</pre>\n"
        "<pre><code class='language-python'>pre-formatted fixed-width code block written in the Python programming language</code></pre>\n\n"
        "<blockquote>Block quotation started\nBlock quotation continued\nThe last line of the block quotation</blockquote>\n"
        "<blockquote expandable>Expandable block quotation started\nExpandable block quotation continued\nExpandable block quotation continued\nHidden by default part of the block quotation started\nExpandable block quotation continued\nThe last line of the block quotation</blockquote>\n"
    )

    await callback.message.answer(text=text)
    # logger.info(
    #     f"{user}\n\n{user.transactions}\n\n{user.server}\n\n{user.activated_promocodes}\n\n"
    # )
    # logger.info(f"{await vpn_service.get_key(user.tg_id)}\n\n")

    # connection = await server_pool_service.get_connection(user.server_id)

    # server = connection.server
    # logger.info(f"{server}\n\n{server.users}\n\n")

    # transaction = await Transaction.get(session=session, payment_id="test")
    # logger.info(f"{transaction}\n\n{transaction.user}")

    # logger.info(server.current_clients)


@router.callback_query(F.data == NavAdminTools.TEST_PURCHASE, IsAdmin())
async def callback_test_purchase(
    callback: CallbackQuery,
    user: User,
    gateway_factory: GatewayFactory,
) -> None:
    logger.info(f"Admin {user.tg_id} initiated test purchase.")

    try:
        gateway = gateway_factory.get_gateway(NavSubscription.PAY_YOOKASSA)
    except ValueError:
        await callback.answer("YooKassa не подключена", show_alert=True)
        return

    data = SubscriptionData(
        state=NavSubscription.PAY_YOOKASSA,
        user_id=user.tg_id,
        devices=5,
        duration=30,
        price=10,
        plan_code="p5wl",
    )

    try:
        pay_url = await gateway.create_payment(data)
    except Exception as e:
        logger.error(f"Test purchase payment creation failed: {e}")
        await callback.answer("Ошибка создания платежа", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Оплатить 10₽", url=pay_url))
    builder.row(InlineKeyboardButton(text="Назад", callback_data=NavAdminTools.MAIN))

    await callback.message.edit_text(
        text=(
            "Тестовая покупка:\n\n"
            "Тариф: 5 устройств + обход БС\n"
            "Срок: 30 дней\n"
            "Цена: 10 ₽"
        ),
        reply_markup=builder.as_markup(),
    )
