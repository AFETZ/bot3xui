from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.bot.models import ClientData

SUBSCRIPTION_SYNC_STATUS_OK = "ok"
SUBSCRIPTION_SYNC_STATUS_MISSING = "missing"
SUBSCRIPTION_SYNC_STATUS_ERROR = "error"
LOCAL_SUBSCRIPTION_STATE_MAX_AGE = timedelta(minutes=20)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def is_subscription_snapshot_fresh(
    user: Any,
    *,
    max_age: timedelta = LOCAL_SUBSCRIPTION_STATE_MAX_AGE,
) -> bool:
    last_synced_at = as_utc(getattr(user, "subscription_last_synced_at", None))
    if last_synced_at is None:
        return False
    return datetime.now(timezone.utc) - last_synced_at <= max_age


def client_data_from_user_snapshot(
    user: Any,
    *,
    require_fresh: bool = True,
    max_age: timedelta = LOCAL_SUBSCRIPTION_STATE_MAX_AGE,
) -> ClientData | None:
    if require_fresh and not is_subscription_snapshot_fresh(user, max_age=max_age):
        return None

    max_devices = getattr(user, "subscription_max_devices", None)
    expiry_time = getattr(user, "subscription_expiry_time", None)
    enabled = getattr(user, "subscription_enabled", None)

    if max_devices is None or expiry_time is None or enabled is None:
        return None

    return ClientData(
        max_devices=max_devices,
        traffic_total=getattr(user, "subscription_traffic_total", None) or -1,
        traffic_remaining=getattr(user, "subscription_traffic_remaining", None) or -1,
        traffic_used=getattr(user, "subscription_traffic_used", None) or 0,
        traffic_up=getattr(user, "subscription_traffic_up", None) or 0,
        traffic_down=getattr(user, "subscription_traffic_down", None) or 0,
        expiry_time=expiry_time,
        enabled=bool(enabled),
    )


def client_data_snapshot_updates(
    client_data: ClientData | None,
    *,
    status: str,
    now: datetime | None = None,
) -> dict[str, object | None]:
    synced_at = now or datetime.now(timezone.utc)

    if client_data is None:
        return {
            "subscription_max_devices": None,
            "subscription_traffic_total": None,
            "subscription_traffic_remaining": None,
            "subscription_traffic_used": None,
            "subscription_traffic_up": None,
            "subscription_traffic_down": None,
            "subscription_expiry_time": None,
            "subscription_enabled": False,
            "subscription_last_synced_at": synced_at,
            "subscription_sync_status": status,
        }

    return {
        "subscription_max_devices": client_data.max_devices_count,
        "subscription_traffic_total": client_data.traffic_total_bytes,
        "subscription_traffic_remaining": client_data.traffic_remaining_bytes,
        "subscription_traffic_used": client_data.traffic_used_bytes,
        "subscription_traffic_up": client_data.traffic_up_bytes,
        "subscription_traffic_down": client_data.traffic_down_bytes,
        "subscription_expiry_time": client_data.expiry_timestamp,
        "subscription_enabled": client_data.enabled,
        "subscription_last_synced_at": synced_at,
        "subscription_sync_status": status,
    }
