from types import SimpleNamespace

import pytest

from app.bot.models.plan import Plan
from app.bot.utils.constants import Currency
from app.bot.utils.navigation import NavSubscription
from app.web.cabinet import CabinetWeb


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
