from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.models.client_data import ClientData
from app.bot.models.plan import Plan
from app.bot.models.subscription_data import SubscriptionData
from app.bot.routers.subscription.subscription_handler import callback_subscription_change
from app.bot.services.subscription import SubscriptionStatus, UpgradeQuote
from app.bot.utils.navigation import NavSubscription


def flatten_keyboard_texts(markup):
    return [button.text for row in markup.inline_keyboard for button in row]


def fake_gettext(message, plural=None, n=1):
    if plural is None:
        return message
    return message if n == 1 else plural


@pytest.fixture(autouse=True)
def patch_i18n(monkeypatch):
    monkeypatch.setattr("app.bot.routers.misc.keyboard._", fake_gettext)
    monkeypatch.setattr("app.bot.routers.subscription.keyboard._", fake_gettext)
    monkeypatch.setattr("app.bot.routers.subscription.subscription_handler._", fake_gettext)
    monkeypatch.setattr("app.bot.utils.formatting._", fake_gettext)


@pytest.mark.asyncio
async def test_change_screen_shows_base_public_tariffs_for_hidden_wl_plan():
    current_hidden_plan = Plan(
        code="p3a",
        devices=3,
        title="Стандарт · 3 устр. + БС",
        is_public=False,
        includes_additional_profile=True,
        upgrade_from="p3",
        prices={"RUB": {30: 549}},
    )
    base_one = Plan(
        code="p1",
        devices=1,
        title="Базовый · 1 устр.",
        prices={"RUB": {30: 299}},
    )
    base_three = Plan(
        code="p3",
        devices=3,
        title="Стандарт · 3 устр.",
        prices={"RUB": {30: 349}},
    )
    base_five = Plan(
        code="p5",
        devices=5,
        title="Семейный · 5 устр.",
        is_popular=True,
        prices={"RUB": {30: 449}},
    )
    wl_one = Plan(
        code="p1wl",
        devices=1,
        title="Базовый · 1 устр. + БС",
        includes_additional_profile=True,
        prices={"RUB": {30: 499}},
    )
    wl_five = Plan(
        code="p5wl",
        devices=5,
        title="Семейный · 5 устр. + БС",
        includes_additional_profile=True,
        prices={"RUB": {30: 599}},
    )

    quotes = [
        UpgradeQuote(
            current_plan=current_hidden_plan,
            target_plan=target_plan,
            price=0,
            renewal_price=target_plan.get_price("RUB", 30),
            renewal_duration_days=30,
            expiry_timestamp=15 * 24 * 60 * 60 * 1000,
        )
        for target_plan in (base_one, base_three, base_five, wl_one, wl_five)
    ]
    status = SubscriptionStatus(
        user=SimpleNamespace(tg_id=1),
        client_data=ClientData(
            max_devices=3,
            traffic_total=0,
            traffic_remaining=0,
            traffic_used=0,
            traffic_up=0,
            traffic_down=0,
            expiry_time=15 * 24 * 60 * 60 * 1000,
        ),
        plan=current_hidden_plan,
        is_active=True,
        status_check_ok=True,
        period_duration_days=30,
        expiry_timestamp=15 * 24 * 60 * 60 * 1000,
    )
    message = SimpleNamespace(edit_text=AsyncMock())
    callback = SimpleNamespace(message=message)
    user = SimpleNamespace(tg_id=1)
    config = SimpleNamespace(shop=SimpleNamespace(CURRENCY="RUB"))
    services = SimpleNamespace(
        subscription=SimpleNamespace(
            get_plan_change_quotes=AsyncMock(return_value=quotes),
            get_subscription_status=AsyncMock(return_value=status),
        ),
        notification=SimpleNamespace(show_popup=AsyncMock()),
    )
    callback_data = SubscriptionData(
        state=NavSubscription.CHANGE,
        user_id=1,
        plan_code=current_hidden_plan.code,
    )

    await callback_subscription_change(
        callback=callback,
        user=user,
        callback_data=callback_data,
        config=config,
        services=services,
    )

    assert message.edit_text.await_count == 1
    kwargs = message.edit_text.await_args.kwargs
    assert "Сменить тариф" in kwargs["text"]

    texts = flatten_keyboard_texts(kwargs["reply_markup"])
    assert any("Базовый · 1 устр." in text for text in texts)
    assert any("Стандарт · 3 устр. | без доплаты" in text for text in texts)
    assert any("Семейный · 5 устр." in text for text in texts)
    assert any("Базовый · 1 устр. + БС" in text for text in texts)
    assert any("Семейный · 5 устр. + БС" in text for text in texts)
    assert not any("Стандарт · 3 устр. + БС" in text for text in texts)
