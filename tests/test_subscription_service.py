from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.models.client_data import ClientData
from app.bot.models.plan import Plan
from app.bot.services.subscription import (
    SubscriptionService,
    SubscriptionStatus,
)
from app.bot.utils.constants import Currency
from app.db.models import User


class DummySessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePlanService:
    def __init__(self, plans):
        self._plans = plans
        self._plans_by_code = {plan.code: plan for plan in plans}

    def get_durations(self):
        return [30, 60, 180, 365]

    def get_plan(self, devices):
        return next(
            (
                plan
                for plan in self._plans
                if plan.devices == devices and plan.is_public
            ),
            None,
        )

    def get_plan_by_code(self, code):
        return self._plans_by_code.get(code)

    def get_upgrade_plan(self, current_plan):
        if isinstance(current_plan, str):
            current_plan = self.get_plan_by_code(current_plan)
        if not current_plan:
            return None
        return next(
            (plan for plan in self._plans if plan.upgrade_from == current_plan.code),
            None,
        )

    def get_plan_changes(self, current_plan, duration, currency):
        if isinstance(current_plan, str):
            current_plan = self.get_plan_by_code(current_plan)
        if not current_plan:
            return []

        current_price = current_plan.get_price(currency=currency, duration=duration)
        return [
            plan
            for plan in self._plans
            if plan.is_public
            and plan.code != current_plan.code
            and plan.get_price(currency=currency, duration=duration) > current_price
        ]


@pytest.fixture
def plan_set():
    current_plan = Plan(
        code="p3",
        devices=3,
        title="3 устройства",
        prices={
            "RUB": {30: 349},
            "USD": {30: 3.49},
            "XTR": {30: 351},
        },
    )
    upgraded_plan = Plan(
        code="p3a",
        devices=3,
        title="3 устройства + доп. профиль",
        is_public=False,
        includes_additional_profile=True,
        upgrade_from="p3",
        prices={
            "RUB": {30: 498},
            "USD": {30: 4.98},
            "XTR": {30: 501},
        },
    )
    five_devices = Plan(
        code="p5",
        devices=5,
        title="5 устройств",
        prices={
            "RUB": {30: 449},
            "USD": {30: 4.49},
            "XTR": {30: 452},
        },
    )
    return current_plan, upgraded_plan, five_devices


@pytest.fixture
def subscription_service(plan_set):
    config = SimpleNamespace(bot=SimpleNamespace(DOMAIN="https://bot.example"))
    vpn_service = SimpleNamespace(get_client_data=AsyncMock())
    plan_service = FakePlanService(plan_set)
    return SubscriptionService(
        config=config,
        session_factory=lambda: DummySessionContext(),
        vpn_service=vpn_service,
        plan_service=plan_service,
    )


def test_calculate_upgrade_price_prorates_additional_premium(subscription_service, plan_set):
    current_plan, upgraded_plan, _ = plan_set

    price = subscription_service.calculate_upgrade_price(
        current_plan=current_plan,
        target_plan=upgraded_plan,
        duration_days=30,
        currency=Currency.RUB,
        remaining_seconds=15 * 24 * 60 * 60,
    )

    assert price == 75


def test_calculate_upgrade_price_uses_full_target_price_when_period_expired(
    subscription_service,
    plan_set,
):
    current_plan, upgraded_plan, _ = plan_set

    price = subscription_service.calculate_upgrade_price(
        current_plan=current_plan,
        target_plan=upgraded_plan,
        duration_days=30,
        currency=Currency.RUB,
        remaining_seconds=0,
    )

    assert price == 498


def test_get_payment_plan_prefers_explicit_plan_code(subscription_service, plan_set):
    _, upgraded_plan, five_devices = plan_set

    resolved = subscription_service.get_payment_plan(
        plan_code=upgraded_plan.code,
        devices=five_devices.devices,
    )

    assert resolved.code == upgraded_plan.code


def test_can_upgrade_plan_only_for_active_non_upgraded_tariff(subscription_service, plan_set):
    current_plan, upgraded_plan, _ = plan_set
    user = SimpleNamespace(tg_id=1)

    active_status = SubscriptionStatus(
        user=user,
        client_data=None,
        plan=current_plan,
        is_active=True,
        status_check_ok=True,
        period_duration_days=30,
        expiry_timestamp=1,
    )
    upgraded_status = SubscriptionStatus(
        user=user,
        client_data=None,
        plan=upgraded_plan,
        is_active=True,
        status_check_ok=True,
        period_duration_days=30,
        expiry_timestamp=1,
    )
    inactive_status = SubscriptionStatus(
        user=user,
        client_data=None,
        plan=current_plan,
        is_active=False,
        status_check_ok=True,
        period_duration_days=30,
        expiry_timestamp=1,
    )

    assert subscription_service.can_upgrade_plan(active_status) is True
    assert subscription_service.can_upgrade_plan(upgraded_status) is False
    assert subscription_service.can_upgrade_plan(inactive_status) is False


@pytest.mark.asyncio
async def test_get_upgrade_quote_uses_remaining_period(monkeypatch, subscription_service, plan_set):
    current_plan, upgraded_plan, _ = plan_set
    user = SimpleNamespace(tg_id=101, vpn_id="vpn-101")
    status = SubscriptionStatus(
        user=user,
        client_data=ClientData(
            max_devices=3,
            traffic_total=0,
            traffic_remaining=0,
            traffic_used=0,
            traffic_up=0,
            traffic_down=0,
            expiry_time=15 * 24 * 60 * 60 * 1000,
        ),
        plan=current_plan,
        is_active=True,
        status_check_ok=True,
        period_duration_days=30,
        expiry_timestamp=15 * 24 * 60 * 60 * 1000,
    )

    monkeypatch.setattr(
        "app.bot.services.subscription.get_current_timestamp",
        lambda: 0,
    )
    subscription_service.get_subscription_status = AsyncMock(return_value=status)

    quote = await subscription_service.get_upgrade_quote(user=user, currency=Currency.RUB)

    assert quote is not None
    assert quote.current_plan.code == "p3"
    assert quote.target_plan.code == "p3a"
    assert quote.price == 75
    assert quote.renewal_price == 498


@pytest.mark.asyncio
async def test_get_plan_change_quotes_prorate_difference_without_period_reset(
    monkeypatch, subscription_service, plan_set
):
    current_plan, _, five_devices = plan_set
    user = SimpleNamespace(tg_id=102, vpn_id="vpn-102")
    expiry_timestamp = 15 * 24 * 60 * 60 * 1000
    status = SubscriptionStatus(
        user=user,
        client_data=ClientData(
            max_devices=3,
            traffic_total=0,
            traffic_remaining=0,
            traffic_used=0,
            traffic_up=0,
            traffic_down=0,
            expiry_time=expiry_timestamp,
        ),
        plan=current_plan,
        is_active=True,
        status_check_ok=True,
        period_duration_days=30,
        expiry_timestamp=expiry_timestamp,
    )

    monkeypatch.setattr(
        "app.bot.services.subscription.get_current_timestamp",
        lambda: 0,
    )
    subscription_service.get_subscription_status = AsyncMock(return_value=status)

    quotes = await subscription_service.get_plan_change_quotes(user=user, currency=Currency.RUB)
    quote_by_code = {quote.target_plan.code: quote for quote in quotes}

    assert quote_by_code[five_devices.code].price == 50
    assert quote_by_code[five_devices.code].expiry_timestamp == expiry_timestamp
    assert quote_by_code[five_devices.code].renewal_duration_days == 30


@pytest.mark.asyncio
async def test_get_plan_change_quotes_keep_zero_price_options(
    monkeypatch, subscription_service, plan_set
):
    current_plan, _, five_devices = plan_set
    user = SimpleNamespace(tg_id=103, vpn_id="vpn-103")
    expiry_timestamp = 3600 * 1000
    status = SubscriptionStatus(
        user=user,
        client_data=ClientData(
            max_devices=3,
            traffic_total=0,
            traffic_remaining=0,
            traffic_used=0,
            traffic_up=0,
            traffic_down=0,
            expiry_time=expiry_timestamp,
        ),
        plan=current_plan,
        is_active=True,
        status_check_ok=True,
        period_duration_days=30,
        expiry_timestamp=expiry_timestamp,
    )

    monkeypatch.setattr(
        "app.bot.services.subscription.get_current_timestamp",
        lambda: 0,
    )
    subscription_service.get_subscription_status = AsyncMock(return_value=status)

    quotes = await subscription_service.get_plan_change_quotes(user=user, currency=Currency.RUB)
    quote_by_code = {quote.target_plan.code: quote for quote in quotes}

    assert five_devices.code in quote_by_code
    assert quote_by_code[five_devices.code].price == 0


@pytest.mark.asyncio
async def test_has_additional_profile_access_checks_entitlement(subscription_service, plan_set):
    _, upgraded_plan, _ = plan_set
    user = SimpleNamespace(tg_id=7)
    status = SubscriptionStatus(
        user=user,
        client_data=None,
        plan=upgraded_plan,
        is_active=True,
        status_check_ok=True,
        period_duration_days=30,
        expiry_timestamp=1,
    )

    subscription_service.get_subscription_status = AsyncMock(return_value=status)

    assert await subscription_service.has_additional_profile_access(user) is True


@pytest.mark.asyncio
async def test_get_subscription_status_by_vpn_id_returns_user_and_status(
    monkeypatch,
    subscription_service,
    plan_set,
):
    current_plan, _, _ = plan_set
    user = SimpleNamespace(
        tg_id=123,
        vpn_id="vpn-123",
        server_id=None,
        current_plan_code="p3",
        current_period_duration_days=30,
    )
    status = SubscriptionStatus(
        user=user,
        client_data=None,
        plan=current_plan,
        is_active=False,
        status_check_ok=True,
        period_duration_days=30,
        expiry_timestamp=None,
    )

    monkeypatch.setattr(User, "get_by_vpn_id", AsyncMock(return_value=user))
    subscription_service.get_subscription_status = AsyncMock(return_value=status)

    resolved_user, resolved_status = await subscription_service.get_subscription_status_by_vpn_id(
        "vpn-123"
    )

    assert resolved_user is user
    assert resolved_status is status


def test_get_additional_profile_url_uses_domain_and_vpn_id(subscription_service):
    user = SimpleNamespace(vpn_id="vpn-500")

    assert subscription_service.get_additional_profile_url(user) == "https://bot.example/wl/vpn-500"
