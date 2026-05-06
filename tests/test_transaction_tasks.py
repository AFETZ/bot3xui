from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.bot.tasks.transactions import reconcile_pending_transactions
from app.bot.utils.constants import TransactionStatus
from app.bot.utils.navigation import NavSubscription


class DummyResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class DummySessionContext:
    def __init__(self, rows):
        self._rows = rows

    async def __aenter__(self):
        return SimpleNamespace(execute=AsyncMock(return_value=DummyResult(self._rows)))

    async def __aexit__(self, exc_type, exc, tb):
        return False


def make_subscription(state: NavSubscription) -> str:
    return f"subscription:{state.value}:0:0:1:5:30:10.0:p5wl:0"


async def test_reconcile_pending_transactions_reconciles_yookassa_only():
    gateway = SimpleNamespace(reconcile_pending_payment=AsyncMock())
    gateway_factory = SimpleNamespace(get_gateway=lambda _: gateway)
    rows = [
        SimpleNamespace(
            payment_id="pay-1",
            status=TransactionStatus.PENDING,
            subscription=make_subscription(NavSubscription.PAY_YOOKASSA),
        ),
        SimpleNamespace(
            payment_id="pay-2",
            status=TransactionStatus.PENDING,
            subscription=make_subscription(NavSubscription.PAY_TELEGRAM_STARS),
        ),
    ]

    await reconcile_pending_transactions(
        session_factory=lambda: DummySessionContext(rows),
        gateway_factory=gateway_factory,
    )

    gateway.reconcile_pending_payment.assert_awaited_once_with("pay-1")


async def test_reconcile_pending_transactions_skips_when_gateway_factory_missing():
    gateway = SimpleNamespace(reconcile_pending_payment=AsyncMock())
    gateway_factory = SimpleNamespace(get_gateway=lambda _: gateway)
    rows = [
        SimpleNamespace(
            payment_id="pay-3",
            status=TransactionStatus.PENDING,
            subscription=make_subscription(NavSubscription.PAY_YOOKASSA),
        )
    ]

    await reconcile_pending_transactions(
        session_factory=lambda: DummySessionContext(rows),
        gateway_factory=None,
    )

    gateway.reconcile_pending_payment.assert_not_awaited()
