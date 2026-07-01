from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import time
import uuid
from typing import Any

from aiohttp import web

from app.bot.models import Plan, ServicesContainer, SubscriptionData
from app.bot.payment_gateways import GatewayFactory, PaymentGateway
from app.bot.routers.download.keyboard import (
    build_connect_url,
    build_happ_routing_connection_url,
)
from app.bot.services.subscription import SubscriptionStatus
from app.bot.utils.constants import APP_IOS_SCHEME, Currency
from app.bot.utils.formatting import normalize_price
from app.bot.utils.navigation import NavSubscription
from app.bot.utils.time import get_current_timestamp
from app.config import BASE_DIR, Config
from app.db.models import User

logger = logging.getLogger(__name__)

NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}
WEB_EXCLUDED_GATEWAYS = {NavSubscription.PAY_TELEGRAM_STARS.value}
WEB_USER_FIRST_NAME = "Web"
WEB_USER_LANGUAGE = "ru"
WEB_USER_TG_ID_MIN = 100_000_000
WEB_USER_TG_ID_RANGE = 900_000_000
ACCOUNT_COOKIE_NAME = "afzvpn_account"
ACCOUNT_SESSION_TTL_SECONDS = 60 * 60 * 24 * 30
PASSWORD_HASH_ITERATIONS = 310_000
LOGIN_PATTERN = re.compile(r"^[A-Za-z0-9_.@+-]{3,128}$")

GATEWAY_LABELS = {
    NavSubscription.PAY_CRYPTOMUS.value: "Cryptomus",
    NavSubscription.PAY_HELEKET.value: "Heleket",
    NavSubscription.PAY_YOOKASSA.value: "YooKassa",
    NavSubscription.PAY_YOOMONEY.value: "YooMoney",
}
VPN_ID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)

TEMPLATE_DIR = BASE_DIR / "web" / "templates"


def _load_template(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")

PUBLIC_TEMPLATE = _load_template("cabinet_public.html")

HTML_TEMPLATE = _load_template("cabinet.html")


def _enum_value(value: object) -> str:
    return getattr(value, "value", str(value))


def _extract_vpn_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    match = VPN_ID_PATTERN.search(value.strip())
    if not match:
        return None

    return match.group(0).lower()


def _generate_web_tg_id() -> int:
    return -((uuid.uuid4().int % WEB_USER_TG_ID_RANGE) + WEB_USER_TG_ID_MIN)


def _normalize_login(value: object) -> str:
    login = str(value or "").strip().lower()
    if not LOGIN_PATTERN.fullmatch(login):
        raise web.HTTPBadRequest(
            text="Логин должен быть от 3 до 128 символов: латиница, цифры, @ . _ + -"
        )
    return login


def _validate_password(value: object) -> str:
    password = str(value or "")
    if len(password) < 8:
        raise web.HTTPBadRequest(text="Пароль должен быть не короче 8 символов.")
    if len(password) > 256:
        raise web.HTTPBadRequest(text="Пароль слишком длинный.")
    return password


def _hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_HASH_ITERATIONS,
    )
    return (
        f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}$"
        f"{salt.hex()}${digest.hex()}"
    )


def _verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False

    try:
        algorithm, iterations_raw, salt_hex, digest_hex = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_raw)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (TypeError, ValueError):
        return False

    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual, expected)


def _duration_label(days: int) -> str:
    if days == 365:
        return "1 год"
    if days > 0 and days % 365 == 0:
        years = days // 365
        return f"{years} года" if years in {2, 3, 4} else f"{years} лет"
    if days == 30:
        return "1 месяц"
    if days > 0 and days % 30 == 0:
        months = days // 30
        if months in {2, 3, 4}:
            return f"{months} месяца"
        return f"{months} месяцев"
    if days % 10 == 1 and days % 100 != 11:
        return f"{days} день"
    if days % 10 in {2, 3, 4} and days % 100 not in {12, 13, 14}:
        return f"{days} дня"
    return f"{days} дней"


def _device_label(devices: int | None) -> str:
    if devices is None:
        return ""
    if devices == -1:
        return "Безлимит устройств"
    if devices == 1:
        return "1 устройство"
    if devices in {2, 3, 4}:
        return f"{devices} устройства"
    return f"{devices} устройств"


def _remaining_days(status: SubscriptionStatus) -> int | None:
    if status.expiry_timestamp is None:
        return None
    remaining_ms = max(status.expiry_timestamp - get_current_timestamp(), 0)
    if remaining_ms <= 0:
        return 0
    return max(1, int((remaining_ms + 86_399_999) // 86_400_000))


class CabinetWeb:
    def __init__(
        self,
        *,
        config: Config,
        services: ServicesContainer,
        gateway_factory: GatewayFactory,
    ) -> None:
        self.config = config
        self.services = services
        self.gateway_factory = gateway_factory

    def _session_signature(self, tg_id: int, expires_at: int) -> str:
        secret = self.config.bot.TOKEN.encode("utf-8")
        payload = f"{tg_id}:{expires_at}".encode("utf-8")
        return hmac.new(secret, payload, hashlib.sha256).hexdigest()

    def _make_session_token(self, user: User) -> str:
        expires_at = int(time.time()) + ACCOUNT_SESSION_TTL_SECONDS
        signature = self._session_signature(user.tg_id, expires_at)
        return f"{user.tg_id}:{expires_at}:{signature}"

    def _is_secure_request(self, request: web.Request) -> bool:
        forwarded_proto = request.headers.get("X-Forwarded-Proto", "").lower()
        return request.secure or forwarded_proto == "https"

    def _set_account_cookie(
        self,
        response: web.StreamResponse,
        request: web.Request,
        user: User,
    ) -> None:
        response.set_cookie(
            ACCOUNT_COOKIE_NAME,
            self._make_session_token(user),
            max_age=ACCOUNT_SESSION_TTL_SECONDS,
            httponly=True,
            secure=self._is_secure_request(request),
            samesite="Lax",
            path="/",
        )

    def _clear_account_cookie(self, response: web.StreamResponse) -> None:
        response.del_cookie(ACCOUNT_COOKIE_NAME, path="/")

    async def _get_account_user(self, request: web.Request) -> User | None:
        token = request.cookies.get(ACCOUNT_COOKIE_NAME)
        if not token:
            return None

        try:
            tg_id_raw, expires_raw, signature = token.split(":", 2)
            tg_id = int(tg_id_raw)
            expires_at = int(expires_raw)
        except (TypeError, ValueError):
            return None

        if expires_at < int(time.time()):
            return None

        expected_signature = self._session_signature(tg_id, expires_at)
        if not hmac.compare_digest(signature, expected_signature):
            return None

        async with self.services.subscription.session_factory() as session:
            user = await User.get(session=session, tg_id=tg_id)

        if not user or not user.web_login:
            return None
        return user

    def _cabinet_url(self, user: User) -> str:
        return self.services.subscription.get_cabinet_url(user)

    def _web_gateways(self) -> list[PaymentGateway]:
        return [
            gateway
            for gateway in self.gateway_factory.get_gateways()
            if _enum_value(gateway.callback) not in WEB_EXCLUDED_GATEWAYS
        ]

    def _gateway_payload(self, gateway: PaymentGateway) -> dict[str, Any]:
        callback = _enum_value(gateway.callback)
        return {
            "id": callback,
            "name": GATEWAY_LABELS.get(callback, str(gateway.name)),
            "currency": gateway.currency.code,
            "symbol": gateway.currency.symbol,
        }

    def _price_for_plan(
        self,
        plan: Plan,
        gateway: PaymentGateway,
        duration: int,
    ) -> float | int | None:
        try:
            return plan.get_price(currency=gateway.currency, duration=duration)
        except (KeyError, ValueError):
            return None

    def _plan_payload(
        self,
        plan: Plan,
        gateways: list[PaymentGateway],
    ) -> dict[str, Any]:
        durations = []
        for duration in plan.get_available_durations(self.services.plan.get_durations()):
            prices = {}
            for gateway in gateways:
                price = self._price_for_plan(plan, gateway, duration)
                if price is None:
                    continue
                prices[_enum_value(gateway.callback)] = {
                    "price": price,
                    "currency": gateway.currency.code,
                    "symbol": gateway.currency.symbol,
                }
            if not prices:
                continue

            try:
                discount_percent = plan.get_discount_percent(
                    currency=Currency.from_code(self.config.shop.CURRENCY),
                    duration=duration,
                )
            except (KeyError, ValueError):
                discount_percent = 0

            durations.append(
                {
                    "days": duration,
                    "label": _duration_label(duration),
                    "discount_percent": discount_percent,
                    "prices": prices,
                }
            )

        return {
            "code": plan.code,
            "title": plan.title or _device_label(plan.devices),
            "devices": plan.devices,
            "devices_label": _device_label(plan.devices),
            "includes_additional_profile": plan.includes_additional_profile,
            "is_popular": plan.is_popular,
            "durations": durations,
        }

    def _status_payload(
        self,
        user: User,
        status: SubscriptionStatus,
    ) -> dict[str, Any]:
        plan = status.plan
        devices = status.client_data.max_devices_count if status.client_data else None
        remaining_days = _remaining_days(status)

        if getattr(user, "is_blocked", False):
            state = "blocked"
            label = "Заблокирована"
            message = "Доступ к подписке ограничен. Оплата в кабинете недоступна."
        elif not status.status_check_ok:
            state = "unavailable"
            label = "Проверка недоступна"
            message = "Не получилось проверить подписку в панели. Попробуйте обновить страницу позже."
        elif status.is_active:
            state = "active"
            label = "Активна"
            message = (
                f"Осталось: {_duration_label(remaining_days)}."
                if remaining_days is not None
                else "Подписка активна."
            )
        elif status.client_data and status.client_data.has_subscription_expired:
            state = "expired"
            label = "Закончилась"
            message = "Оплатите тариф, и старая ссылка снова начнет работать."
        else:
            state = "not_active"
            label = "Не активна"
            message = "Выберите тариф и оплатите подключение."

        return {
            "state": state,
            "label": label,
            "message": message,
            "plan_code": plan.code if plan else "",
            "plan_title": plan.title if plan and plan.title else _device_label(devices),
            "expiry_date": status.expiry_date,
            "remaining_days": remaining_days,
            "devices": devices,
            "devices_label": _device_label(devices),
            "has_additional_profile": status.has_additional_profile,
        }

    async def _quote_prices(
        self,
        *,
        user: User,
        target_plan: Plan | None = None,
    ) -> dict[str, dict[str, Any]]:
        prices = {}
        for gateway in self._web_gateways():
            quote = await self.services.subscription.get_upgrade_quote(
                user=user,
                currency=gateway.currency,
                target_plan=target_plan,
            )
            if not quote:
                continue

            price = self.services.subscription.apply_personal_discount(
                user=user,
                price=quote.price,
                currency=gateway.currency,
            )
            prices[_enum_value(gateway.callback)] = {
                "price": price,
                "currency": gateway.currency.code,
                "symbol": gateway.currency.symbol,
            }
        return prices

    async def _quote_payload(
        self,
        *,
        user: User,
        quote,
        currency: Currency,
    ) -> dict[str, Any]:
        price = self.services.subscription.apply_personal_discount(
            user=user,
            price=quote.price,
            currency=currency,
        )
        return {
            "target_plan": self._plan_payload(quote.target_plan, self._web_gateways()),
            "price": price,
            "currency": currency.code,
            "currency_symbol": currency.symbol,
            "renewal_price": quote.renewal_price,
            "renewal_duration_days": quote.renewal_duration_days,
            "expiry_date": quote.expiry_date,
            "prices": await self._quote_prices(user=user, target_plan=quote.target_plan),
        }

    async def _resolve_user_status(
        self,
        request: web.Request,
    ) -> tuple[User, SubscriptionStatus]:
        vpn_id = request.match_info["vpn_id"]
        user, status = await self.services.subscription.get_subscription_status_by_vpn_id(
            vpn_id
        )
        if not user or not status:
            raise web.HTTPNotFound(text="Кабинет не найден.")
        return user, status

    async def public_page(self, _: web.Request) -> web.Response:
        return web.Response(
            text=PUBLIC_TEMPLATE,
            content_type="text/html",
            charset="utf-8",
            headers={
                **NO_STORE_HEADERS,
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
            },
        )

    async def page(self, request: web.Request) -> web.Response:
        api_base = json.dumps(f"/cabinet/{request.match_info['vpn_id']}/api")
        html = HTML_TEMPLATE.replace("__API_BASE__", api_base)
        return web.Response(
            text=html,
            content_type="text/html",
            charset="utf-8",
            headers={
                **NO_STORE_HEADERS,
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
            },
        )

    async def state(self, request: web.Request) -> web.Response:
        user, status = await self._resolve_user_status(request)
        account_user = await self._get_account_user(request)
        gateways = self._web_gateways()
        shop_currency = Currency.from_code(self.config.shop.CURRENCY)

        purchase_plans = []
        if not status.is_active and not getattr(user, "is_blocked", False):
            purchase_plans = [
                self._plan_payload(plan, gateways)
                for plan in self.services.plan.get_all_plans(
                    prefer_additional_profile=not user.server_id
                    and not user.current_plan_code,
                )
            ]
            purchase_plans = [plan for plan in purchase_plans if plan["durations"]]

        renew = None
        if status.is_active and status.plan:
            renew_plan = status.plan
            renew_payload = self._plan_payload(renew_plan, gateways)
            if renew_payload["durations"]:
                renew = {"plan": renew_payload}

        change = None
        if status.is_active:
            quotes = await self.services.subscription.get_plan_change_quotes(
                user=user,
                currency=shop_currency,
            )
            quote_payloads = [
                await self._quote_payload(
                    user=user,
                    quote=quote,
                    currency=shop_currency,
                )
                for quote in quotes
            ]
            change = {"quotes": quote_payloads}

        upgrade = None
        if status.is_active and self.services.subscription.can_upgrade_plan(status):
            quote = await self.services.subscription.get_upgrade_quote(
                user=user,
                currency=shop_currency,
            )
            if quote:
                upgrade = await self._quote_payload(
                    user=user,
                    quote=quote,
                    currency=shop_currency,
                )

        primary_profile_url = await self.services.vpn.get_key(user)
        additional_profile_url = (
            self.services.subscription.get_additional_profile_url(user)
            if status.has_additional_profile
            else None
        )
        get_filtered_additional_profile_url = getattr(
            self.services.subscription,
            "get_filtered_additional_profile_url",
            None,
        )
        filtered_additional_profile_url = (
            get_filtered_additional_profile_url(user)
            if status.has_additional_profile and get_filtered_additional_profile_url
            else None
        )

        def _happ_connect(profile_url: str | None) -> str | None:
            if not profile_url:
                return None
            # Root-relative so the deep-link redirect resolves on whichever
            # domain serves the cabinet, mirroring the bot's connect button.
            return build_connect_url(
                url="",
                scheme=APP_IOS_SCHEME,
                key=profile_url,
                platform_param="web",
            )

        connect_links = {
            "primary": _happ_connect(primary_profile_url),
            "filtered_additional": _happ_connect(filtered_additional_profile_url),
            "additional": _happ_connect(additional_profile_url),
            "routing": build_happ_routing_connection_url(url="", platform_param="web"),
        }

        return web.json_response(
            {
                "cabinet_url": self._cabinet_url(user),
                "user": {"name": user.first_name},
                "account": {
                    "authenticated": bool(
                        account_user and account_user.tg_id == user.tg_id
                    ),
                    "login": (
                        account_user.web_login
                        if account_user and account_user.tg_id == user.tg_id
                        else ""
                    ),
                    "current_account_url": (
                        self._cabinet_url(account_user) if account_user else ""
                    ),
                },
                "status": self._status_payload(user, status),
                "links": {
                    "primary_profile_url": primary_profile_url,
                    "additional_profile_url": additional_profile_url,
                    "filtered_additional_profile_url": filtered_additional_profile_url,
                },
                "connect": connect_links,
                "gateways": [self._gateway_payload(gateway) for gateway in gateways],
                "purchase": {"plans": purchase_plans},
                "renew": renew,
                "upgrade": upgrade,
                "change": change,
            },
            headers=NO_STORE_HEADERS,
        )

    async def public_state(self, _: web.Request) -> web.Response:
        gateways = self._web_gateways()
        purchase_plans = [
            self._plan_payload(plan, gateways)
            for plan in self.services.plan.get_all_plans(
                prefer_additional_profile=True,
            )
        ]
        purchase_plans = [plan for plan in purchase_plans if plan["durations"]]

        return web.json_response(
            {
                "gateways": [self._gateway_payload(gateway) for gateway in gateways],
                "purchase": {"plans": purchase_plans},
            },
            headers=NO_STORE_HEADERS,
        )

    async def me(self, request: web.Request) -> web.Response:
        account_user = await self._get_account_user(request)
        return web.json_response(
            {
                "authenticated": bool(account_user),
                "login": account_user.web_login if account_user else "",
                "cabinet_url": self._cabinet_url(account_user) if account_user else "",
            },
            headers=NO_STORE_HEADERS,
        )

    async def _read_json(self, request: web.Request) -> dict[str, Any]:
        try:
            payload = await request.json()
        except ValueError as exception:
            raise web.HTTPBadRequest(text="Некорректный запрос.") from exception

        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="Некорректный запрос.")
        return payload

    async def _create_web_user(
        self,
        *,
        web_login: str | None = None,
        web_password_hash: str | None = None,
    ) -> User:
        async with self.services.subscription.session_factory() as session:
            return await self._create_web_user_in_session(
                session=session,
                web_login=web_login,
                web_password_hash=web_password_hash,
            )

    async def _create_web_user_in_session(
        self,
        *,
        session,
        web_login: str | None = None,
        web_password_hash: str | None = None,
    ) -> User:
        for _ in range(10):
            user = await User.create(
                session=session,
                tg_id=_generate_web_tg_id(),
                vpn_id=str(uuid.uuid4()),
                first_name=(web_login or WEB_USER_FIRST_NAME)[:32],
                username="web",
                web_login=web_login,
                web_password_hash=web_password_hash,
                language_code=WEB_USER_LANGUAGE,
            )
            if user:
                return user

        raise web.HTTPInternalServerError(text="Не удалось создать кабинет.")

    async def login(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        login = _normalize_login(payload.get("login"))
        password = str(payload.get("password") or "")

        async with self.services.subscription.session_factory() as session:
            user = await User.get_by_web_login(session=session, web_login=login)

        if not user or not _verify_password(password, user.web_password_hash):
            raise web.HTTPUnauthorized(text="Неверный логин или пароль.")

        response = web.json_response(
            {"cabinet_url": self._cabinet_url(user)},
            headers=NO_STORE_HEADERS,
        )
        self._set_account_cookie(response, request, user)
        return response

    async def register(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        login = _normalize_login(payload.get("login"))
        password = _validate_password(payload.get("password"))
        key_value = str(payload.get("key") or "").strip()
        password_hash = _hash_password(password)

        async with self.services.subscription.session_factory() as session:
            existing = await User.get_by_web_login(session=session, web_login=login)
            if existing:
                raise web.HTTPConflict(text="Этот логин уже занят.")

            target_user = None
            vpn_id = _extract_vpn_id(key_value)
            if vpn_id:
                target_user = await User.get_by_vpn_id(session=session, vpn_id=vpn_id)
                if not target_user:
                    raise web.HTTPNotFound(text="Подписка по этой ссылке не найдена.")
                if target_user.web_login:
                    raise web.HTTPConflict(text="Эта подписка уже привязана к аккаунту.")

            if target_user:
                await User.update(
                    session=session,
                    tg_id=target_user.tg_id,
                    web_login=login,
                    web_password_hash=password_hash,
                    first_name=target_user.first_name or login[:32],
                )
                user = await User.get(session=session, tg_id=target_user.tg_id)
            else:
                user = await self._create_web_user_in_session(
                    session=session,
                    web_login=login,
                    web_password_hash=password_hash,
                )

        if not user:
            raise web.HTTPInternalServerError(text="Не удалось создать аккаунт.")

        response = web.json_response(
            {"cabinet_url": self._cabinet_url(user)},
            headers=NO_STORE_HEADERS,
        )
        self._set_account_cookie(response, request, user)
        return response

    async def logout(self, _: web.Request) -> web.Response:
        response = web.json_response(
            {"ok": True, "cabinet_url": "/cabinet"},
            headers=NO_STORE_HEADERS,
        )
        self._clear_account_cookie(response)
        return response

    @staticmethod
    def _has_subscription_or_payments(user: User) -> bool:
        return bool(
            user.server_id
            or user.current_plan_code
            or getattr(user, "transactions", None)
        )

    async def bind_key(self, request: web.Request) -> web.Response:
        account_user = await self._get_account_user(request)
        if not account_user:
            raise web.HTTPUnauthorized(text="Сначала войдите в аккаунт.")

        payload = await self._read_json(request)
        vpn_id = _extract_vpn_id(payload.get("value"))
        if not vpn_id:
            raise web.HTTPBadRequest(text="Вставьте полную ссылку подписки.")

        async with self.services.subscription.session_factory() as session:
            current = await User.get(session=session, tg_id=account_user.tg_id)
            target = await User.get_by_vpn_id(session=session, vpn_id=vpn_id)
            if not current:
                raise web.HTTPUnauthorized(text="Сначала войдите в аккаунт.")
            if not target:
                raise web.HTTPNotFound(text="Подписка по этой ссылке не найдена.")
            if target.tg_id == current.tg_id:
                user = target
            elif target.web_login:
                raise web.HTTPConflict(text="Эта подписка уже привязана к аккаунту.")
            elif self._has_subscription_or_payments(current):
                raise web.HTTPConflict(
                    text="К этому аккаунту уже привязана другая подписка."
                )
            else:
                login = current.web_login
                password_hash = current.web_password_hash
                if not login or not password_hash:
                    raise web.HTTPUnauthorized(text="Сначала войдите в аккаунт.")

                await User.update(
                    session=session,
                    tg_id=current.tg_id,
                    web_login=None,
                    web_password_hash=None,
                )
                await User.update(
                    session=session,
                    tg_id=target.tg_id,
                    web_login=login,
                    web_password_hash=password_hash,
                )
                user = await User.get(session=session, tg_id=target.tg_id)

        if not user:
            raise web.HTTPInternalServerError(text="Не удалось привязать подписку.")

        response = web.json_response(
            {"cabinet_url": self._cabinet_url(user)},
            headers=NO_STORE_HEADERS,
        )
        self._set_account_cookie(response, request, user)
        return response

    async def start_purchase(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        gateway_id = str(payload.get("gateway") or "")
        gateway = self._get_web_gateway(gateway_id)
        user = await self._get_account_user(request)
        if user:
            status = await self.services.subscription.get_subscription_status(user)
            if status.is_active:
                raise web.HTTPConflict(
                    text="Для продления откройте свой кабинет и выберите продление."
                )
        else:
            user = await self._create_web_user()
        data = await self._build_payment_data(
            user=user,
            status=type("InactiveStatus", (), {"is_active": False})(),
            payload={**payload, "mode": "purchase"},
            gateway=gateway,
        )

        cabinet_url = self._cabinet_url(user)
        pay_url = await gateway.create_payment(data, return_url=cabinet_url)
        logger.info(
            "Web cabinet new purchase link created for web user %s gateway=%s.",
            user.tg_id,
            gateway_id,
        )
        return web.json_response(
            {
                "pay_url": pay_url,
                "cabinet_url": cabinet_url,
            },
            headers=NO_STORE_HEADERS,
        )

    async def resolve(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        vpn_id = _extract_vpn_id(payload.get("value"))
        if not vpn_id:
            raise web.HTTPBadRequest(text="Вставьте полную ссылку подписки или кабинета.")

        user, _ = await self.services.subscription.get_subscription_status_by_vpn_id(
            vpn_id
        )
        if not user:
            raise web.HTTPNotFound(text="Кабинет по этой ссылке не найден.")

        return web.json_response(
            {"cabinet_url": self._cabinet_url(user)},
            headers=NO_STORE_HEADERS,
        )

    def _get_web_gateway(self, gateway_id: str) -> PaymentGateway:
        gateway_ids = {_enum_value(gateway.callback) for gateway in self._web_gateways()}
        if gateway_id not in gateway_ids:
            raise web.HTTPBadRequest(text="Этот способ оплаты недоступен в кабинете.")

        try:
            return self.gateway_factory.get_gateway(gateway_id)
        except ValueError as exception:
            raise web.HTTPBadRequest(text="Этот способ оплаты недоступен.") from exception

    def _get_plan(self, plan_code: str | None, devices: int = 0) -> Plan:
        plan = self.services.subscription.get_payment_plan(
            plan_code=plan_code,
            devices=devices,
        )
        if not plan:
            raise web.HTTPBadRequest(text="Тариф не найден.")
        return plan

    def _get_duration(self, payload: dict[str, Any], plan: Plan) -> int:
        try:
            duration = int(payload.get("duration") or 0)
        except (TypeError, ValueError) as exception:
            raise web.HTTPBadRequest(text="Срок тарифа не выбран.") from exception

        available_durations = plan.get_available_durations(self.services.plan.get_durations())
        if duration not in available_durations:
            raise web.HTTPBadRequest(text="Этот срок недоступен для тарифа.")
        return duration

    def _payment_state(self, gateway: PaymentGateway) -> NavSubscription:
        return NavSubscription(_enum_value(gateway.callback))

    async def _build_payment_data(
        self,
        *,
        user: User,
        status: SubscriptionStatus,
        payload: dict[str, Any],
        gateway: PaymentGateway,
    ) -> SubscriptionData:
        mode = str(payload.get("mode") or "purchase")
        plan_code = str(payload.get("plan_code") or "")

        if mode == "extend" and not status.is_active:
            mode = "purchase"

        if mode == "purchase":
            if status.is_active:
                raise web.HTTPBadRequest(text="Для активной подписки используйте продление.")
            plan = self._get_plan(plan_code)
            duration = self._get_duration(payload, plan)
            price = self._price_for_plan(plan, gateway, duration)
            if price is None:
                raise web.HTTPBadRequest(text="Этот способ оплаты недоступен для тарифа.")
            price = self.services.subscription.apply_personal_discount(
                user=user,
                price=price,
                currency=gateway.currency,
            )
            return SubscriptionData(
                state=self._payment_state(gateway),
                user_id=user.tg_id,
                devices=plan.devices,
                duration=duration,
                price=price,
                plan_code=plan.code,
            )

        if mode == "extend":
            if not status.is_active:
                raise web.HTTPBadRequest(text="Подписка не активна.")
            plan = status.plan or self._get_plan(plan_code)
            duration = self._get_duration(payload, plan)
            price = self._price_for_plan(plan, gateway, duration)
            if price is None:
                raise web.HTTPBadRequest(text="Этот способ оплаты недоступен для тарифа.")
            price = self.services.subscription.apply_personal_discount(
                user=user,
                price=price,
                currency=gateway.currency,
            )
            return SubscriptionData(
                state=self._payment_state(gateway),
                is_extend=True,
                user_id=user.tg_id,
                devices=plan.devices,
                duration=duration,
                price=price,
                plan_code=plan.code,
            )

        if mode == "change":
            if not status.is_active:
                raise web.HTTPBadRequest(text="Смена тарифа доступна только активной подписке.")
            target_plan = self.services.plan.get_plan_by_code(plan_code)
            if not target_plan:
                raise web.HTTPBadRequest(text="Тариф не найден.")
            quote = await self.services.subscription.get_upgrade_quote(
                user=user,
                currency=gateway.currency,
                target_plan=target_plan,
            )
            if not quote:
                raise web.HTTPBadRequest(text="Смена тарифа сейчас недоступна.")
            price = self.services.subscription.apply_personal_discount(
                user=user,
                price=quote.price,
                currency=gateway.currency,
            )
            if price <= 0:
                raise web.HTTPBadRequest(text="Этот переход не требует оплаты.")
            return SubscriptionData(
                state=self._payment_state(gateway),
                is_change=True,
                user_id=user.tg_id,
                devices=target_plan.devices,
                duration=quote.renewal_duration_days,
                price=price,
                plan_code=target_plan.code,
            )

        if mode == "upgrade":
            if not status.is_active:
                raise web.HTTPBadRequest(text="Опция доступна только активной подписке.")
            quote = await self.services.subscription.get_upgrade_quote(
                user=user,
                currency=gateway.currency,
            )
            if not quote:
                raise web.HTTPBadRequest(text="Подключение опции сейчас недоступно.")
            price = self.services.subscription.apply_personal_discount(
                user=user,
                price=quote.price,
                currency=gateway.currency,
            )
            if price <= 0:
                raise web.HTTPBadRequest(text="Этот переход не требует оплаты.")
            return SubscriptionData(
                state=self._payment_state(gateway),
                is_upgrade=True,
                user_id=user.tg_id,
                devices=quote.target_plan.devices,
                duration=quote.renewal_duration_days,
                price=price,
                plan_code=quote.target_plan.code,
            )

        raise web.HTTPBadRequest(text="Неизвестное действие.")

    async def pay(self, request: web.Request) -> web.Response:
        user, status = await self._resolve_user_status(request)
        if getattr(user, "is_blocked", False):
            raise web.HTTPForbidden(text="Оплата недоступна.")
        if not status.status_check_ok:
            raise web.HTTPServiceUnavailable(text="Проверка подписки временно недоступна.")

        payload = await self._read_json(request)
        gateway_id = str(payload.get("gateway") or "")
        gateway = self._get_web_gateway(gateway_id)
        data = await self._build_payment_data(
            user=user,
            status=status,
            payload=payload,
            gateway=gateway,
        )

        pay_url = await gateway.create_payment(
            data,
            return_url=self._cabinet_url(user),
        )
        logger.info(
            "Web cabinet payment link created for user %s mode=%s gateway=%s.",
            user.tg_id,
            payload.get("mode"),
            gateway_id,
        )
        return web.json_response({"pay_url": pay_url}, headers=NO_STORE_HEADERS)

    async def apply_change(self, request: web.Request) -> web.Response:
        user, status = await self._resolve_user_status(request)
        if getattr(user, "is_blocked", False):
            raise web.HTTPForbidden(text="Смена тарифа недоступна.")
        if not status.status_check_ok or not status.is_active:
            raise web.HTTPBadRequest(text="Смена тарифа доступна только активной подписке.")

        payload = await self._read_json(request)
        plan_code = str(payload.get("plan_code") or "")
        target_plan = self.services.plan.get_plan_by_code(plan_code)
        if not target_plan:
            raise web.HTTPBadRequest(text="Тариф не найден.")

        quote = await self.services.subscription.get_upgrade_quote(
            user=user,
            currency=Currency.from_code(self.config.shop.CURRENCY),
            target_plan=target_plan,
        )
        if not quote or normalize_price(quote.price, self.config.shop.CURRENCY) != 0:
            raise web.HTTPBadRequest(text="Этот переход требует оплаты.")

        success = await self.services.vpn.change_subscription(
            user=user,
            devices=target_plan.devices,
        )
        if not success:
            raise web.HTTPBadRequest(text="Не удалось сменить тариф.")

        await self.services.subscription.update_current_plan(
            user=user,
            plan_code=target_plan.code,
            refresh_period=False,
        )
        logger.info(
            "Web cabinet applied free plan change for user %s to plan %s.",
            user.tg_id,
            target_plan.code,
        )
        return web.json_response({"ok": True}, headers=NO_STORE_HEADERS)


def setup_cabinet_routes(
    app: web.Application,
    *,
    config: Config,
    services: ServicesContainer,
    gateway_factory: GatewayFactory,
) -> None:
    cabinet = CabinetWeb(
        config=config,
        services=services,
        gateway_factory=gateway_factory,
    )
    assets_dir = BASE_DIR / "assets"
    if assets_dir.exists():
        app.router.add_static("/assets/", assets_dir, name="assets")
    app.router.add_get("/cabinet", cabinet.public_page)
    app.router.add_post("/cabinet/resolve", cabinet.resolve)
    app.router.add_get("/cabinet/api/public", cabinet.public_state)
    app.router.add_get("/cabinet/api/me", cabinet.me)
    app.router.add_post("/cabinet/api/login", cabinet.login)
    app.router.add_post("/cabinet/api/register", cabinet.register)
    app.router.add_post("/cabinet/api/logout", cabinet.logout)
    app.router.add_post("/cabinet/api/bind", cabinet.bind_key)
    app.router.add_post("/cabinet/api/start", cabinet.start_purchase)
    app.router.add_get("/cabinet/{vpn_id}", cabinet.page)
    app.router.add_get("/cabinet/{vpn_id}/api/state", cabinet.state)
    app.router.add_post("/cabinet/{vpn_id}/api/pay", cabinet.pay)
    app.router.add_post("/cabinet/{vpn_id}/api/change/apply", cabinet.apply_change)
