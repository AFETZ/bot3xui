from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.tasks import subscription_expiry


class DummySessionFactory:
    def __call__(self):
        return self

    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return None


class FakeRedis:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.set_calls = []

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex=None):
        self.values[key] = value
        self.set_calls.append((key, value, ex))


class FakeI18n:
    def gettext(self, key, locale=None):
        return f"{key}: {{devices}} {{expiry_time}}"


class FakeVPNService:
    def __init__(self, client_data_by_tg_id):
        self.client_data_by_tg_id = client_data_by_tg_id

    async def get_client_data(self, user):
        return self.client_data_by_tg_id[user.tg_id]


class FakeNotificationService:
    def __init__(self):
        self.messages = []

    async def notify_by_id(self, chat_id, text):
        self.messages.append((chat_id, text))


def _expiry_ms(hours_left: int) -> int:
    expiry = datetime.now(timezone.utc) + timedelta(hours=hours_left)
    return int(expiry.timestamp() * 1000)


def _client_data(expiry_time: int):
    return SimpleNamespace(
        _expiry_time=expiry_time,
        max_devices=3,
        expiry_time="2 ч.",
    )


async def _run_task(monkeypatch, client_data, redis):
    user = SimpleNamespace(tg_id=123, language_code="ru")
    notification_service = FakeNotificationService()

    monkeypatch.setattr(
        subscription_expiry.User,
        "get_all",
        AsyncMock(return_value=[user]),
    )

    await subscription_expiry.notify_users_with_expiring_subscription(
        session_factory=DummySessionFactory(),
        redis=redis,
        i18n=FakeI18n(),
        vpn_service=FakeVPNService({user.tg_id: client_data}),
        notification_service=notification_service,
    )

    return notification_service


@pytest.mark.asyncio
async def test_expiring_in_20_hours_uses_regular_notification(monkeypatch):
    expiry_time = _expiry_ms(20)
    redis = FakeRedis()

    notification_service = await _run_task(
        monkeypatch,
        client_data=_client_data(expiry_time),
        redis=redis,
    )

    assert notification_service.messages == [
        (123, "task:message:subscription_expiry: 3 2 ч.")
    ]
    assert redis.set_calls == [
        (
            "user:notified:subscription_expiry:123:"
            f"{expiry_time}:24h",
            "true",
            subscription_expiry.EXPIRY_NOTIFICATION_TTL,
        )
    ]


@pytest.mark.asyncio
async def test_expiring_in_2_hours_uses_urgent_notification(monkeypatch):
    expiry_time = _expiry_ms(2)
    redis = FakeRedis()

    notification_service = await _run_task(
        monkeypatch,
        client_data=_client_data(expiry_time),
        redis=redis,
    )

    assert notification_service.messages == [
        (123, "task:message:subscription_expiry_urgent: 3 2 ч.")
    ]
    assert redis.set_calls[0][0] == (
        "user:notified:subscription_expiry:123:" f"{expiry_time}:3h"
    )


@pytest.mark.asyncio
async def test_urgent_notification_is_sent_after_regular_notification(monkeypatch):
    expiry_time = _expiry_ms(2)
    regular_key = "user:notified:subscription_expiry:123:" f"{expiry_time}:24h"
    redis = FakeRedis({regular_key: "true"})

    notification_service = await _run_task(
        monkeypatch,
        client_data=_client_data(expiry_time),
        redis=redis,
    )

    assert notification_service.messages == [
        (123, "task:message:subscription_expiry_urgent: 3 2 ч.")
    ]
    assert redis.set_calls[0][0] == (
        "user:notified:subscription_expiry:123:" f"{expiry_time}:3h"
    )


@pytest.mark.asyncio
async def test_legacy_regular_notification_key_does_not_block_urgent(monkeypatch):
    expiry_time = _expiry_ms(2)
    redis = FakeRedis({"user:notified:123": "true"})

    notification_service = await _run_task(
        monkeypatch,
        client_data=_client_data(expiry_time),
        redis=redis,
    )

    assert notification_service.messages == [
        (123, "task:message:subscription_expiry_urgent: 3 2 ч.")
    ]
    assert redis.set_calls[0][0] == (
        "user:notified:subscription_expiry:123:" f"{expiry_time}:3h"
    )


@pytest.mark.asyncio
async def test_legacy_regular_notification_key_blocks_regular_duplicate(monkeypatch):
    expiry_time = _expiry_ms(20)
    redis = FakeRedis({"user:notified:123": "true"})

    notification_service = await _run_task(
        monkeypatch,
        client_data=_client_data(expiry_time),
        redis=redis,
    )

    assert notification_service.messages == []
    assert redis.set_calls == []


@pytest.mark.asyncio
async def test_already_sent_urgent_notification_is_not_duplicated(monkeypatch):
    expiry_time = _expiry_ms(2)
    urgent_key = "user:notified:subscription_expiry:123:" f"{expiry_time}:3h"
    redis = FakeRedis({urgent_key: "true"})

    notification_service = await _run_task(
        monkeypatch,
        client_data=_client_data(expiry_time),
        redis=redis,
    )

    assert notification_service.messages == []
    assert redis.set_calls == []
