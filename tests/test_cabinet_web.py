from types import SimpleNamespace

import pytest

from app.bot.models.plan import Plan
from app.bot.utils.constants import Currency
from app.bot.utils.navigation import NavSubscription
from app.web.cabinet import (
    CabinetWeb,
    _extract_vpn_id,
    _generate_web_tg_id,
    _hash_password,
    _normalize_login,
    _verify_password,
)


class FakePlanService:
    def __init__(self, *plans):
        self.plans = {plan.code: plan for plan in plans}

    def get_durations(self):
        return [30]

    def get_all_plans(self, *, prefer_additional_profile=False):
        return list(self.plans.values())

    def get_plan_by_code(self, code):
        return self.plans.get(code)


class FakeSubscriptionService:
    def __init__(self, plan):
        self.plan = plan

    def get_payment_plan(self, plan_code, devices):
        return self.plan if plan_code == self.plan.code or devices == self.plan.devices else None

    def apply_personal_discount(self, *, user, price, currency):
        return price

    def get_cabinet_url(self, user):
        return f"https://bot.example/cabinet/{user.vpn_id}"


class FakeGatewayFactory:
    def __init__(self, *gateways):
        self.gateways = list(gateways)
        self.by_callback = {gateway.callback.value: gateway for gateway in gateways}

    def get_gateways(self):
        return self.gateways

    def get_gateway(self, name):
        return self.by_callback[name]


@pytest.fixture
def plan():
    return Plan(
        code="p3",
        devices=3,
        title="Стандарт",
        prices={
            "RUB": {30: 349},
            "XTR": {30: 351},
        },
    )


@pytest.fixture
def yookassa_gateway():
    return SimpleNamespace(
        callback=NavSubscription.PAY_YOOKASSA,
        currency=Currency.RUB,
        name="YooKassa",
    )


@pytest.fixture
def stars_gateway():
    return SimpleNamespace(
        callback=NavSubscription.PAY_TELEGRAM_STARS,
        currency=Currency.XTR,
        name="Stars",
    )


@pytest.fixture
def cabinet(plan, yookassa_gateway, stars_gateway):
    services = SimpleNamespace(
        plan=FakePlanService(plan),
        subscription=FakeSubscriptionService(plan),
        vpn=SimpleNamespace(),
    )
    return CabinetWeb(
        config=SimpleNamespace(shop=SimpleNamespace(CURRENCY="RUB")),
        services=services,
        gateway_factory=FakeGatewayFactory(yookassa_gateway, stars_gateway),
    )


def test_cabinet_excludes_telegram_stars_from_web_gateways(cabinet):
    callbacks = [gateway.callback for gateway in cabinet._web_gateways()]

    assert callbacks == [NavSubscription.PAY_YOOKASSA]


def test_extract_vpn_id_accepts_existing_subscription_links():
    vpn_id = "4df8e0dd-4a59-45d8-b28e-9b3eaefba880"

    assert _extract_vpn_id(f"https://example.test/sub/{vpn_id}") == vpn_id
    assert _extract_vpn_id(f"https://example.test/cabinet/{vpn_id}") == vpn_id
    assert _extract_vpn_id(f"https://example.test/wl/{vpn_id}") == vpn_id


def test_extract_vpn_id_rejects_unknown_values():
    assert _extract_vpn_id("https://example.test/cabinet/not-a-real-id") is None


def test_generate_web_tg_id_uses_compact_negative_ids():
    tg_id = _generate_web_tg_id()

    assert -1_000_000_000 < tg_id <= -100_000_000


def test_normalize_login_accepts_email_like_login():
    assert _normalize_login(" Client+1@Example.COM ") == "client+1@example.com"


def test_password_hash_verifies_only_matching_password():
    password_hash = _hash_password("strong-password")

    assert _verify_password("strong-password", password_hash) is True
    assert _verify_password("wrong-password", password_hash) is False


@pytest.mark.asyncio
async def test_cabinet_builds_purchase_payment_data_for_inactive_user(
    cabinet,
    plan,
    yookassa_gateway,
):
    user = SimpleNamespace(tg_id=123, vpn_id="vpn-1", personal_discount_percent=0)
    status = SimpleNamespace(is_active=False)

    data = await cabinet._build_payment_data(
        user=user,
        status=status,
        payload={"mode": "purchase", "plan_code": plan.code, "duration": 30},
        gateway=yookassa_gateway,
    )

    assert data.state == NavSubscription.PAY_YOOKASSA
    assert data.user_id == 123
    assert data.plan_code == plan.code
    assert data.devices == 3
    assert data.duration == 30
    assert data.price == 349
    assert data.is_extend is False


@pytest.mark.asyncio
async def test_cabinet_builds_extend_payment_data_for_active_user(
    cabinet,
    plan,
    yookassa_gateway,
):
    user = SimpleNamespace(tg_id=123, vpn_id="vpn-1", personal_discount_percent=0)
    status = SimpleNamespace(is_active=True, plan=plan)

    data = await cabinet._build_payment_data(
        user=user,
        status=status,
        payload={"mode": "extend", "plan_code": "ignored", "duration": 30},
        gateway=yookassa_gateway,
    )

    assert data.state == NavSubscription.PAY_YOOKASSA
    assert data.plan_code == plan.code
    assert data.devices == 3
    assert data.duration == 30
    assert data.price == 349
    assert data.is_extend is True
