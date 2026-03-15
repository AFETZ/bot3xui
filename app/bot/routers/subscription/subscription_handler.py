import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import ServicesContainer, SubscriptionData
from app.bot.payment_gateways import GatewayFactory
from app.bot.utils.constants import Currency
from app.bot.utils.formatting import format_device_count, format_subscription_period
from app.bot.utils.navigation import NavSubscription
from app.config import Config
from app.db.models import User

from .keyboard import (
    additional_profile_keyboard,
    devices_keyboard,
    duration_keyboard,
    pay_keyboard,
    payment_method_keyboard,
    subscription_keyboard,
    upgrade_offer_keyboard,
)

logger = logging.getLogger(__name__)
router = Router(name=__name__)


def _build_upgrade_offer_text(quote, currency_symbol: str) -> str:
    return (
        "Улучшить тариф\n\n"
        f"Новый тариф: {quote.target_plan.title or format_device_count(quote.target_plan.devices)}\n"
        f"Доплата за оставшийся период: {quote.price} {currency_symbol}\n"
        f"После {quote.expiry_date} продление на {format_subscription_period(quote.renewal_duration_days)} "
        f"будет по цене {quote.renewal_price} {currency_symbol}"
    )


def _get_plan_title(status) -> str:
    if status.plan and status.plan.title:
        return status.plan.title
    if status.client_data:
        return format_device_count(status.client_data.max_devices_count)
    return "-"


def _build_subscription_text(status) -> str:
    if status.is_active and status.client_data:
        lines = [
            "Моя подписка",
            f"Текущий тариф: {_get_plan_title(status)}",
            f"Активна до: {status.expiry_date}",
            "",
        ]

        if status.has_additional_profile:
            lines.extend(
                [
                    "Основной профиль:",
                    "Дополнительный профиль:",
                    "",
                ]
            )

        lines.append("Доступные действия:")
        return "\n".join(lines)

    if status.client_data and status.client_data.has_subscription_expired:
        return _("subscription:message:expired")

    return _("subscription:message:not_active")


def _build_additional_profile_text(
    status,
    *,
    quote=None,
    currency_symbol: str = "",
    show_test_purchase: bool = False,
) -> str:
    if status.has_additional_profile:
        return (
            "Доп. профиль\n\n"
            "Статус: подключен\n"
            f"Текущий тариф: {_get_plan_title(status)}\n"
            f"Активна до: {status.expiry_date}\n\n"
            "Ссылки на основной и дополнительный профили доступны ниже."
        )

    if quote:
        return (
            "Доп. профиль\n\n"
            "Эта опция доступна на вашем текущем тарифе сразу после улучшения.\n"
            f"Новый тариф: {quote.target_plan.title or format_device_count(quote.target_plan.devices)}\n"
            f"Доплата за оставшийся период: {quote.price} {currency_symbol}\n"
            f"После {quote.expiry_date} продление на "
            f"{format_subscription_period(quote.renewal_duration_days)} будет по цене "
            f"{quote.renewal_price} {currency_symbol}"
        )

    if status.is_active:
        return (
            "Доп. профиль\n\n"
            "Опция доступна для активных тарифов от 3 устройств.\n"
            "Откройте раздел подписки, чтобы выбрать подходящий тариф."
        )

    if show_test_purchase:
        return (
            "Доп. профиль\n\n"
            "Для проверки доступна временная тестовая покупка:\n"
            "3 месяца + доп. профиль через YooKassa за 1 ₽.\n\n"
            "После оплаты сразу появятся основной и дополнительный профили."
        )

    return (
        "Доп. профиль\n\n"
        "Опция становится доступной после оформления активной подписки "
        "на тариф от 3 устройств."
    )


async def show_subscription(
    callback: CallbackQuery,
    user: User,
    status,
    callback_data: SubscriptionData,
    services: ServicesContainer,
) -> None:
    show_upgrade = services.subscription.can_upgrade_plan(status)
    show_change = bool(status.is_active and not show_upgrade and not status.has_additional_profile)
    additional_profile_url = (
        services.subscription.get_additional_profile_url(user)
        if status.has_additional_profile
        else None
    )

    await callback.message.edit_text(
        text=_build_subscription_text(status),
        reply_markup=subscription_keyboard(
            has_subscription=status.is_active,
            callback_data=callback_data,
            show_change=show_change,
            show_upgrade=show_upgrade,
            show_primary_profile=status.has_additional_profile,
            additional_profile_url=additional_profile_url,
        ),
    )


@router.callback_query(F.data == NavSubscription.MAIN)
async def callback_subscription(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    logger.info(f"User {user.tg_id} opened subscription page.")
    await state.set_state(None)

    status = await services.subscription.get_subscription_status(user)
    callback_data = SubscriptionData(
        state=NavSubscription.PROCESS,
        user_id=user.tg_id,
        plan_code=status.plan.code if status.plan else "",
    )
    await show_subscription(
        callback=callback,
        user=user,
        status=status,
        callback_data=callback_data,
        services=services,
    )


@router.callback_query(F.data == NavSubscription.ADDITIONAL_PROFILE)
async def callback_additional_profile(
    callback: CallbackQuery,
    user: User,
    config: Config,
    services: ServicesContainer,
) -> None:
    logger.info("User %s opened additional profile page.", user.tg_id)
    status = await services.subscription.get_subscription_status(user)
    additional_profile_url = (
        services.subscription.get_additional_profile_url(user)
        if status.has_additional_profile
        else None
    )

    upgrade_callback_data = None
    quote = None
    show_test_purchase = bool(
        not status.is_active and config.shop.PAYMENT_YOOKASSA_ENABLED
    )
    if services.subscription.can_upgrade_plan(status):
        quote = await services.subscription.get_upgrade_quote(
            user=user,
            currency=Currency.from_code(config.shop.CURRENCY),
        )
        upgrade_callback_data = SubscriptionData(
            state=NavSubscription.UPGRADE,
            user_id=user.tg_id,
            plan_code=status.plan.code if status.plan else "",
        ).pack()

    await callback.message.edit_text(
        text=_build_additional_profile_text(
            status,
            quote=quote,
            currency_symbol=Currency.from_code(config.shop.CURRENCY).symbol,
            show_test_purchase=show_test_purchase,
        ),
        reply_markup=additional_profile_keyboard(
            additional_profile_url=additional_profile_url,
            upgrade_callback_data=upgrade_callback_data,
            test_purchase_callback=(
                NavSubscription.ADDITIONAL_PROFILE_TEST_PURCHASE
                if show_test_purchase
                else None
            ),
            show_primary_profile=status.has_additional_profile,
        ),
    )


@router.callback_query(F.data == NavSubscription.ADDITIONAL_PROFILE_TEST_PURCHASE)
async def callback_additional_profile_test_purchase(
    callback: CallbackQuery,
    user: User,
    services: ServicesContainer,
    gateway_factory: GatewayFactory,
) -> None:
    logger.info("User %s started temporary YooKassa test purchase for additional profile.", user.tg_id)
    status = await services.subscription.get_subscription_status(user)
    if status.is_active:
        await services.notification.show_popup(
            callback=callback,
            text="Тестовая покупка доступна только без активной подписки.",
        )
        return

    try:
        gateway = gateway_factory.get_gateway(NavSubscription.PAY_YOOKASSA)
    except ValueError:
        await services.notification.show_popup(
            callback=callback,
            text="YooKassa сейчас недоступна.",
        )
        return

    callback_data = SubscriptionData(
        state=NavSubscription.PAY_YOOKASSA,
        user_id=user.tg_id,
        devices=3,
        duration=90,
        price=1,
        plan_code="p3a",
    )
    pay_url = await gateway.create_payment(callback_data)

    await callback.message.edit_text(
        text=(
            "Тестовая покупка\n\n"
            "Тариф: 3 устройства + доп. профиль\n"
            "Срок: 3 месяца\n"
            "Стоимость: 1 ₽\n"
            "Способ оплаты: YooKassa\n\n"
            "После успешной оплаты подписка активируется сразу."
        ),
        reply_markup=pay_keyboard(pay_url=pay_url, callback_data=callback_data),
    )


@router.callback_query(SubscriptionData.filter(F.state == NavSubscription.EXTEND))
async def callback_subscription_extend(
    callback: CallbackQuery,
    user: User,
    callback_data: SubscriptionData,
    config: Config,
    services: ServicesContainer,
) -> None:
    logger.info(f"User {user.tg_id} started extend subscription.")
    status = await services.subscription.get_subscription_status(user)
    if not status.status_check_ok or not status.client_data or not status.is_active:
        await services.notification.show_popup(
            callback=callback,
            text=_("subscription:popup:error_fetching_data"),
        )
        return

    current_plan = status.plan or services.plan.get_plan(status.client_data.max_devices_count)
    if not current_plan:
        await services.notification.show_popup(
            callback=callback,
            text=_("subscription:popup:error_fetching_plan"),
        )
        return

    callback_data.devices = status.client_data.max_devices_count
    callback_data.plan_code = current_plan.code
    callback_data.state = NavSubscription.DURATION
    callback_data.is_extend = True
    callback_data.is_change = False
    callback_data.is_upgrade = False
    await callback.message.edit_text(
        text=_("subscription:message:duration"),
        reply_markup=duration_keyboard(
            plan_service=services.plan,
            callback_data=callback_data,
            currency=config.shop.CURRENCY,
        ),
    )


@router.callback_query(SubscriptionData.filter(F.state == NavSubscription.CHANGE))
async def callback_subscription_change(
    callback: CallbackQuery,
    user: User,
    callback_data: SubscriptionData,
    services: ServicesContainer,
) -> None:
    logger.info(f"User {user.tg_id} started change subscription.")
    callback_data.state = NavSubscription.DEVICES
    callback_data.is_change = True
    callback_data.is_extend = False
    callback_data.is_upgrade = False
    callback_data.plan_code = ""
    await callback.message.edit_text(
        text=_("subscription:message:devices"),
        reply_markup=devices_keyboard(services.plan.get_all_plans(), callback_data),
    )


@router.callback_query(SubscriptionData.filter(F.state == NavSubscription.PROCESS))
async def callback_subscription_process(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    callback_data: SubscriptionData,
    services: ServicesContainer,
) -> None:
    logger.info(f"User {user.tg_id} started subscription process.")
    server = await services.server_pool.get_available_server()

    if not server:
        await services.notification.show_popup(
            callback=callback,
            text=_("subscription:popup:no_available_servers"),
            cache_time=120,
        )
        return

    callback_data.state = NavSubscription.DEVICES
    callback_data.plan_code = ""
    await callback.message.edit_text(
        text=_("subscription:message:devices"),
        reply_markup=devices_keyboard(services.plan.get_all_plans(), callback_data),
    )


@router.callback_query(SubscriptionData.filter(F.state == NavSubscription.DEVICES))
async def callback_devices_selected(
    callback: CallbackQuery,
    user: User,
    callback_data: SubscriptionData,
    config: Config,
    services: ServicesContainer,
) -> None:
    logger.info(f"User {user.tg_id} selected devices: {callback_data.devices}")
    plan = services.plan.get_plan(callback_data.devices)
    callback_data.plan_code = plan.code if plan else ""
    callback_data.state = NavSubscription.DURATION
    await callback.message.edit_text(
        text=_("subscription:message:duration"),
        reply_markup=duration_keyboard(
            plan_service=services.plan,
            callback_data=callback_data,
            currency=config.shop.CURRENCY,
        ),
    )


@router.callback_query(SubscriptionData.filter(F.state == NavSubscription.DURATION))
async def callback_duration_selected(
    callback: CallbackQuery,
    user: User,
    callback_data: SubscriptionData,
    services: ServicesContainer,
    gateway_factory: GatewayFactory,
) -> None:
    logger.info(f"User {user.tg_id} selected duration: {callback_data.duration}")
    plan = services.subscription.get_payment_plan(
        plan_code=callback_data.plan_code,
        devices=callback_data.devices,
    )
    if not plan:
        await services.notification.show_popup(
            callback=callback,
            text=_("subscription:popup:error_fetching_plan"),
        )
        return

    callback_data.state = NavSubscription.PAY
    await callback.message.edit_text(
        text=_("subscription:message:payment_method"),
        reply_markup=payment_method_keyboard(
            plan=plan,
            callback_data=callback_data,
            gateways=gateway_factory.get_gateways(),
        ),
    )


@router.callback_query(SubscriptionData.filter(F.state == NavSubscription.UPGRADE))
async def callback_subscription_upgrade(
    callback: CallbackQuery,
    user: User,
    callback_data: SubscriptionData,
    config: Config,
    services: ServicesContainer,
) -> None:
    logger.info("User %s opened tariff upgrade offer.", user.tg_id)
    currency = Currency.from_code(config.shop.CURRENCY)
    quote = await services.subscription.get_upgrade_quote(user=user, currency=currency)
    if not quote:
        await services.notification.show_popup(
            callback=callback,
            text="Улучшение тарифа сейчас недоступно.",
        )
        return

    callback_data.state = NavSubscription.UPGRADE
    callback_data.devices = quote.target_plan.devices
    callback_data.duration = quote.renewal_duration_days
    callback_data.plan_code = quote.target_plan.code
    callback_data.price = float(quote.price)
    callback_data.is_extend = False
    callback_data.is_change = False
    callback_data.is_upgrade = True

    await callback.message.edit_text(
        text=_build_upgrade_offer_text(quote, currency.symbol),
        reply_markup=upgrade_offer_keyboard(callback_data),
    )


@router.callback_query(SubscriptionData.filter(F.state == NavSubscription.UPGRADE_PAYMENT))
async def callback_subscription_upgrade_payment(
    callback: CallbackQuery,
    user: User,
    callback_data: SubscriptionData,
    config: Config,
    services: ServicesContainer,
    gateway_factory: GatewayFactory,
) -> None:
    logger.info("User %s selected payment screen for tariff upgrade.", user.tg_id)
    status = await services.subscription.get_subscription_status(user)
    current_plan = status.plan
    target_plan = services.plan.get_upgrade_plan(current_plan)
    if not status.status_check_ok or not status.is_active or not current_plan or not target_plan:
        await services.notification.show_popup(
            callback=callback,
            text="Улучшение тарифа сейчас недоступно.",
        )
        return

    shop_currency = Currency.from_code(config.shop.CURRENCY)
    display_quote = await services.subscription.get_upgrade_quote(user=user, currency=shop_currency)
    if not display_quote:
        await services.notification.show_popup(
            callback=callback,
            text="Улучшение тарифа сейчас недоступно.",
        )
        return

    prices_by_callback: dict[str, float | int] = {}
    for gateway in gateway_factory.get_gateways():
        gateway_quote = await services.subscription.get_upgrade_quote(
            user=user,
            currency=gateway.currency,
        )
        if gateway_quote:
            prices_by_callback[gateway.callback] = gateway_quote.price

    callback_data.state = NavSubscription.UPGRADE_PAYMENT
    callback_data.devices = target_plan.devices
    callback_data.duration = display_quote.renewal_duration_days
    callback_data.plan_code = target_plan.code
    callback_data.price = float(display_quote.price)
    callback_data.is_extend = False
    callback_data.is_change = False
    callback_data.is_upgrade = True

    await callback.message.edit_text(
        text=_build_upgrade_offer_text(display_quote, shop_currency.symbol),
        reply_markup=payment_method_keyboard(
            plan=target_plan,
            callback_data=callback_data,
            gateways=gateway_factory.get_gateways(),
            prices_by_callback=prices_by_callback,
        ),
    )
