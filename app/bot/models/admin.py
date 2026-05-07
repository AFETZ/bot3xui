from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from math import ceil
from typing import Literal

AdminStatisticsPeriod = Literal["today", "7d", "30d", "all"]
AdminUserFilter = Literal["all", "paid", "trial", "inactive", "search"]


@dataclass(slots=True)
class AdminStatisticsOverview:
    period_code: AdminStatisticsPeriod
    generated_at: datetime
    total_users: int
    new_users: int
    paid_users_total: int
    current_paid_users: int
    current_trial_users: int
    inactive_paid_users: int
    inactive_free_users: int
    trial_used_total: int
    completed_transactions_total: int
    completed_transactions_period: int
    revenue_period: dict[str, float] = field(default_factory=dict)
    total_servers: int = 0
    online_servers: int = 0
    total_capacity: int = 0
    total_connected: int = 0
    total_referrals: int = 0
    referrals_period: int = 0

    @property
    def server_load_percent(self) -> int:
        if self.total_capacity <= 0:
            return 0
        return round((self.total_connected / self.total_capacity) * 100)


@dataclass(slots=True)
class AdminUserEditorOverview:
    total_users: int
    paid_users: int
    trial_users: int
    inactive_users: int
    new_users_7d: int


@dataclass(slots=True)
class AdminUserListItem:
    tg_id: int
    first_name: str
    username: str | None
    current_plan_code: str | None
    has_paid: bool
    created_at: datetime

    @property
    def display_name(self) -> str:
        return f"@{self.username}" if self.username else self.first_name


@dataclass(slots=True)
class AdminUserListPage:
    filter_type: AdminUserFilter
    page: int
    limit: int
    total: int
    items: list[AdminUserListItem]

    @property
    def pages(self) -> int:
        if self.total <= 0 or self.limit <= 0:
            return 1
        return ceil(self.total / self.limit)


@dataclass(slots=True)
class AdminUserDetails:
    tg_id: int
    first_name: str
    username: str | None
    vpn_id: str
    created_at: datetime
    language_code: str
    server_name: str | None
    subscription_status_ok: bool
    subscription_active: bool
    subscription_plan_code: str | None
    expiry_timestamp: int | None
    traffic_used: str | None
    devices: str | int | None
    total_transactions: int
    completed_transactions: int
    first_payment_at: datetime | None
    last_payment_at: datetime | None
    revenue_by_currency: dict[str, float]
    referral_count: int
    referrer_tg_id: int | None
    trial_used: bool
    source_invite_name: str | None
    is_blocked: bool = False
    personal_discount_percent: int = 0
    server_host: str | None = None
    server_online: bool | None = None
    activated_promocodes: list[str] = field(default_factory=list)
    latest_transactions: list[str] = field(default_factory=list)
