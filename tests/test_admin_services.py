from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.bot.models.client_data import ClientData
from app.bot.models.subscription_data import SubscriptionData
from app.bot.services.admin_statistics import AdminStatisticsService
from app.bot.services.admin_users import AdminUserService
from app.bot.services.payment_stats import PaymentStatsService
from app.bot.services.subscription import SubscriptionStatus
from app.bot.utils.constants import TransactionStatus
from app.bot.utils.navigation import NavSubscription
from app.db.models import Base, Referral, Server, Transaction, User


def _pack_subscription(user_id: int, price: float, plan_code: str = "p1") -> str:
    return SubscriptionData(
        state=NavSubscription.PAY_YOOKASSA,
        user_id=user_id,
        devices=1,
        duration=30,
        price=price,
        plan_code=plan_code,
    ).pack()


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def seeded_session(session_factory):
    now = datetime.utcnow()

    async with session_factory() as session:
        online_server = Server(
            name="nl-1",
            host="1.1.1.1",
            max_clients=10,
            online=True,
        )
        offline_server = Server(
            name="de-1",
            host="2.2.2.2",
            max_clients=5,
            online=False,
        )

        users = [
            User(
                tg_id=1001,
                vpn_id="vpn-paid-current",
                first_name="Alice",
                username="alice",
                current_plan_code="p1",
                created_at=now - timedelta(days=2),
                server=online_server,
                is_trial_used=True,
            ),
            User(
                tg_id=1002,
                vpn_id="vpn-paid-inactive",
                first_name="Bob",
                username="bob",
                current_plan_code=None,
                created_at=now - timedelta(days=40),
            ),
            User(
                tg_id=1003,
                vpn_id="vpn-trial",
                first_name="Carol",
                username="carol",
                current_plan_code="trial",
                created_at=now - timedelta(days=1),
                server=offline_server,
            ),
            User(
                tg_id=1004,
                vpn_id="vpn-free",
                first_name="Dave",
                username="dave",
                current_plan_code=None,
                created_at=now - timedelta(days=3),
            ),
            User(
                tg_id=1005,
                vpn_id="vpn-old-ref",
                first_name="Eve",
                username="eve",
                current_plan_code=None,
                created_at=now - timedelta(days=60),
            ),
        ]
        session.add_all([online_server, offline_server, *users])

        session.add_all(
            [
                Transaction(
                    tg_id=1001,
                    payment_id="pay-recent",
                    subscription=_pack_subscription(1001, 100),
                    status=TransactionStatus.COMPLETED,
                    created_at=now - timedelta(days=2),
                ),
                Transaction(
                    tg_id=1002,
                    payment_id="pay-old",
                    subscription=_pack_subscription(1002, 200),
                    status=TransactionStatus.COMPLETED,
                    created_at=now - timedelta(days=50),
                ),
                Referral(
                    referrer_tg_id=1001,
                    referred_tg_id=1003,
                    created_at=now - timedelta(days=1),
                ),
                Referral(
                    referrer_tg_id=1001,
                    referred_tg_id=1005,
                    created_at=now - timedelta(days=45),
                ),
            ]
        )

        await session.commit()
        yield session


@pytest.mark.asyncio
async def test_admin_statistics_overview_aggregates_segments_and_period_revenue(
    session_factory,
    seeded_session,
):
    payment_stats = PaymentStatsService(session_factory=session_factory)
    service = AdminStatisticsService(
        session_factory=session_factory,
        payment_stats_service=payment_stats,
    )

    overview = await service.get_overview(
        period_code="7d",
        session=seeded_session,
        payment_method_currencies={NavSubscription.PAY_YOOKASSA.value: "RUB"},
    )

    assert overview.total_users == 5
    assert overview.new_users == 3
    assert overview.paid_users_total == 2
    assert overview.current_paid_users == 1
    assert overview.current_trial_users == 1
    assert overview.inactive_paid_users == 1
    assert overview.inactive_free_users == 2
    assert overview.trial_used_total == 1
    assert overview.completed_transactions_total == 2
    assert overview.completed_transactions_period == 1
    assert overview.revenue_period == {"RUB": 100.0}
    assert overview.total_servers == 2
    assert overview.online_servers == 1
    assert overview.total_capacity == 15
    assert overview.total_connected == 2
    assert overview.server_load_percent == 13
    assert overview.total_referrals == 2
    assert overview.referrals_period == 1


@pytest.mark.asyncio
async def test_admin_user_service_paginates_and_searches_users(
    session_factory,
    seeded_session,
):
    payment_stats = PaymentStatsService(session_factory=session_factory)
    fake_subscription = SimpleNamespace(get_subscription_status=AsyncMock())
    service = AdminUserService(
        session_factory=session_factory,
        subscription_service=fake_subscription,
        payment_stats_service=payment_stats,
    )

    overview = await service.get_editor_overview(session=seeded_session)
    paid_page = await service.get_user_page(
        filter_type="paid",
        page=0,
        limit=1,
        session=seeded_session,
    )
    second_paid_page = await service.get_user_page(
        filter_type="paid",
        page=1,
        limit=1,
        session=seeded_session,
    )
    search_results = await service.search_users(
        query_text="@alice",
        session=seeded_session,
    )
    search_by_vpn = await service.search_users(
        query_text="vpn-trial",
        session=seeded_session,
    )

    assert overview.total_users == 5
    assert overview.paid_users == 2
    assert overview.trial_users == 1
    assert overview.inactive_users == 2
    assert overview.new_users_7d == 3

    assert paid_page.total == 2
    assert paid_page.pages == 2
    assert [item.tg_id for item in paid_page.items] == [1001]
    assert [item.tg_id for item in second_paid_page.items] == [1002]

    assert [item.tg_id for item in search_results] == [1001]
    assert [item.tg_id for item in search_by_vpn] == [1003]


@pytest.mark.asyncio
async def test_admin_user_service_builds_user_details_with_billing_context(
    session_factory,
    seeded_session,
):
    payment_stats = PaymentStatsService(session_factory=session_factory)

    async def get_subscription_status(user):
        return SubscriptionStatus(
            user=user,
            client_data=ClientData(
                max_devices=3,
                traffic_total=0,
                traffic_remaining=0,
                traffic_used=2 * 1024**3,
                traffic_up=0,
                traffic_down=0,
                expiry_time=-1,
            ),
            plan=SimpleNamespace(code="p1"),
            is_active=True,
            status_check_ok=True,
            period_duration_days=30,
            expiry_timestamp=-1,
        )

    service = AdminUserService(
        session_factory=session_factory,
        subscription_service=SimpleNamespace(
            get_subscription_status=AsyncMock(side_effect=get_subscription_status)
        ),
        payment_stats_service=payment_stats,
    )

    details = await service.get_user_details(
        tg_id=1001,
        session=seeded_session,
        payment_method_currencies={NavSubscription.PAY_YOOKASSA.value: "RUB"},
    )

    assert details is not None
    assert details.subscription_active is True
    assert details.subscription_plan_code == "p1"
    assert details.devices == 3
    assert details.traffic_used == "2 GB"
    assert details.completed_transactions == 1
    assert details.total_transactions == 1
    assert details.revenue_by_currency == {"RUB": 100.0}
    assert details.referral_count == 2
    assert details.referrer_tg_id is None
