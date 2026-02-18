import asyncio
import logging

from aiogram import Bot
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.utils.i18n import I18n
from aiogram.utils.i18n import gettext as _
from aiogram.utils.i18n import lazy_gettext as __
from aiohttp.web import Application, Request, Response
from sqlalchemy.ext.asyncio import async_sessionmaker
from yookassa import Configuration, Payment
from yookassa.domain.common import SecurityHelper
from yookassa.domain.common.confirmation_type import ConfirmationType
from yookassa.domain.models.receipt import Receipt, ReceiptItem
from yookassa.domain.notification import (
    WebhookNotificationEventType,
    WebhookNotificationFactory,
)
from yookassa.domain.request.payment_request import PaymentRequest

from app.bot.models import ServicesContainer, SubscriptionData
from app.bot.payment_gateways import PaymentGateway
from app.bot.utils.constants import YOOKASSA_WEBHOOK, Currency, TransactionStatus
from app.bot.utils.formatting import format_device_count, format_subscription_period
from app.bot.utils.navigation import NavSubscription
from app.config import Config
from app.db.models import Transaction

logger = logging.getLogger(__name__)


class Yookassa(PaymentGateway):
    name = ""
    currency = Currency.RUB
    callback = NavSubscription.PAY_YOOKASSA

    def __init__(
        self,
        app: Application,
        config: Config,
        session: async_sessionmaker,
        storage: RedisStorage,
        bot: Bot,
        i18n: I18n,
        services: ServicesContainer,
    ) -> None:
        self.name = __("payment:gateway:yookassa")
        self.app = app
        self.config = config
        self.session = session
        self.storage = storage
        self.bot = bot
        self.i18n = i18n
        self.services = services

        Configuration.configure(self.config.yookassa.SHOP_ID, self.config.yookassa.TOKEN)
        self.app.router.add_post(YOOKASSA_WEBHOOK, self.webhook_handler)
        logger.info("YooKassa payment gateway initialized.")

    async def create_payment(self, data: SubscriptionData) -> str:
        bot_username = (await self.bot.get_me()).username
        redirect_url = f"https://t.me/{bot_username}"

        description = _("payment:invoice:description").format(
            devices=format_device_count(data.devices),
            duration=format_subscription_period(data.duration),
        )

        price = str(data.price)

        receipt = Receipt(
            customer={"email": self.config.shop.EMAIL},
            items=[
                ReceiptItem(
                    description=description,
                    quantity=1,
                    amount={"value": price, "currency": self.currency.code},
                    vat_code=1,
                )
            ],
        )

        request = PaymentRequest(
            amount={"value": price, "currency": self.currency.code},
            confirmation={"type": ConfirmationType.REDIRECT, "return_url": redirect_url},
            capture=True,
            save_payment_method=False,
            description=description,
            receipt=receipt,
        )

        response = Payment.create(request)

        async with self.session() as session:
            await Transaction.create(
                session=session,
                tg_id=data.user_id,
                subscription=data.pack(),
                payment_id=response.id,
                status=TransactionStatus.PENDING,
            )

        pay_url = response.confirmation["confirmation_url"]
        logger.info(f"Payment link created for user {data.user_id}: {pay_url}")
        return pay_url

    async def handle_payment_succeeded(self, payment_id: str) -> None:
        await self._on_payment_succeeded(payment_id)

    async def handle_payment_canceled(self, payment_id: str) -> None:
        await self._on_payment_canceled(payment_id)

    @staticmethod
    def _extract_source_ip(request: Request) -> tuple[str, str, str]:
        x_forwarded_for = request.headers.get("X-Forwarded-For", "")
        remote_ip = request.remote or ""

        # Traefik may pass X-Forwarded-For as a comma-separated chain.
        ip = x_forwarded_for.split(",")[0].strip() if x_forwarded_for else remote_ip
        return ip, x_forwarded_for, remote_ip

    @staticmethod
    def _normalize_status(value: object) -> str:
        if hasattr(value, "value"):
            return str(getattr(value, "value")).lower()
        return str(value).lower()

    async def _is_event_confirmed_by_api(
        self,
        payment_id: str,
        event: WebhookNotificationEventType,
    ) -> bool:
        try:
            payment = await asyncio.to_thread(Payment.find_one, payment_id)
        except Exception as exception:
            logger.exception(
                "YooKassa webhook: failed to verify payment %s via API: %s",
                payment_id,
                exception,
            )
            return False

        status = self._normalize_status(payment.status)
        paid = bool(getattr(payment, "paid", False))

        if event == WebhookNotificationEventType.PAYMENT_SUCCEEDED:
            is_valid = status == "succeeded" and paid
        elif event == WebhookNotificationEventType.PAYMENT_CANCELED:
            is_valid = status == "canceled"
        else:
            is_valid = False

        if not is_valid:
            logger.warning(
                "YooKassa webhook validation failed for payment %s: event=%s api_status=%s paid=%s",
                payment_id,
                event,
                status,
                paid,
            )

        return is_valid

    async def webhook_handler(self, request: Request) -> Response:
        try:
            event_json = await request.json()
            notification_object = WebhookNotificationFactory().create(event_json)
            response_object = notification_object.object
            payment_id = response_object.id
            if not payment_id:
                logger.warning("YooKassa webhook rejected: payment_id is missing.")
                return Response(status=400)

            source_ip, x_forwarded_for, remote_ip = self._extract_source_ip(request)
            source_ip_trusted = bool(source_ip) and SecurityHelper().is_ip_trusted(source_ip)

            if not source_ip_trusted:
                logger.warning(
                    "YooKassa webhook source is not trusted by SDK list (ip='%s', X-Forwarded-For='%s', remote='%s'). Falling back to API verification.",
                    source_ip,
                    x_forwarded_for,
                    remote_ip,
                )

            if not await self._is_event_confirmed_by_api(payment_id, notification_object.event):
                return Response(status=403)

            logger.info(
                "YooKassa webhook received: event=%s payment_id=%s",
                notification_object.event,
                payment_id,
            )

            match notification_object.event:
                case WebhookNotificationEventType.PAYMENT_SUCCEEDED:
                    await self.handle_payment_succeeded(payment_id)
                    return Response(status=200)

                case WebhookNotificationEventType.PAYMENT_CANCELED:
                    await self.handle_payment_canceled(payment_id)
                    return Response(status=200)

                case _:
                    return Response(status=400)

        except Exception as exception:
            logger.exception(f"Error processing YooKassa webhook: {exception}")
            return Response(status=400)
