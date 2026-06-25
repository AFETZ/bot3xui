from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiohttp.web import Application

from app.bot.payment_gateways import PaymentGateway
from app.bot.utils.constants import Currency


class FakeRedis:
    def __init__(self, values=None):
        self.values = dict(values or {})

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def delete(self, key):
        self.values.pop(key, None)


class DummyGateway(PaymentGateway):
    name = "dummy"
    currency = Currency.RUB
    callback = "pay_dummy"

    async def create_payment(self, data, return_url=None):
        return "https://pay.example"

    async def handle_payment_succeeded(self, payment_id):
        await self._on_payment_succeeded(payment_id)

    async def handle_payment_canceled(self, payment_id):
        await self._on_payment_canceled(payment_id)


def _gateway(redis):
    return DummyGateway(
        app=Application(),
        config=SimpleNamespace(),
        session=None,
        storage=SimpleNamespace(redis=redis),
        bot=None,
        i18n=None,
        services=SimpleNamespace(),
    )


async def test_successful_payment_processing_skips_when_lock_exists(monkeypatch):
    gateway = _gateway(FakeRedis({"payment:process:pay-1": "other-token"}))
    process = AsyncMock()
    monkeypatch.setattr(gateway, "_process_payment_succeeded", process)

    await gateway._on_payment_succeeded("pay-1")

    process.assert_not_awaited()


async def test_successful_payment_processing_acquires_lock(monkeypatch):
    redis = FakeRedis()
    gateway = _gateway(redis)
    process = AsyncMock()
    monkeypatch.setattr(gateway, "_process_payment_succeeded", process)

    await gateway._on_payment_succeeded("pay-1")

    process.assert_awaited_once_with("pay-1")
    assert "payment:process:pay-1" not in redis.values
