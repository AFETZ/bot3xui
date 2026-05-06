from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.bot.utils.constants import Currency


@dataclass
class Plan:
    code: str
    devices: int
    prices: dict[str, dict[int, float]]
    title: str | None = None
    durations: list[int] | None = None
    is_public: bool = True
    includes_additional_profile: bool = False
    upgrade_from: str | None = None
    is_popular: bool = False

    @property
    def commercial_key(self) -> tuple[int, bool]:
        return (self.devices, self.includes_additional_profile)

    def same_commercial_offer(self, other: "Plan | None") -> bool:
        if other is None:
            return False
        return self.commercial_key == other.commercial_key

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Plan":
        devices = data["devices"]
        code = data.get("code") or f"p{devices}"
        return cls(
            code=code,
            devices=devices,
            prices={k: {int(m): p for m, p in v.items()} for k, v in data["prices"].items()},
            title=data.get("title"),
            durations=data.get("durations"),
            is_public=data.get("is_public", True),
            includes_additional_profile=data.get("includes_additional_profile", False),
            upgrade_from=data.get("upgrade_from"),
            is_popular=data.get("is_popular", False),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "devices": self.devices,
            "prices": {k: {str(m): p for m, p in v.items()} for k, v in self.prices.items()},
            "title": self.title,
            "durations": self.durations,
            "is_public": self.is_public,
            "includes_additional_profile": self.includes_additional_profile,
            "upgrade_from": self.upgrade_from,
            "is_popular": self.is_popular,
        }

    def get_price(self, currency: Currency | str, duration: int) -> float:
        if isinstance(currency, str):
            currency = Currency.from_code(currency)

        return self.prices[currency.code][duration]

    def get_available_durations(self, default_durations: list[int] | None = None) -> list[int]:
        if self.durations:
            return self.durations

        if default_durations is not None:
            return default_durations

        first_currency_prices = next(iter(self.prices.values()), {})
        return sorted(first_currency_prices.keys())

    @staticmethod
    def _get_duration_periods(duration: int) -> int | None:
        if duration == 365:
            return 12
        if duration > 0 and duration % 30 == 0:
            return duration // 30
        return None

    def get_discount_percent(self, currency: Currency | str, duration: int) -> int:
        periods = self._get_duration_periods(duration)
        if not periods or periods <= 1:
            return 0

        monthly_price = self.get_price(currency=currency, duration=30)
        current_price = self.get_price(currency=currency, duration=duration)
        full_price = Decimal(str(monthly_price)) * Decimal(str(periods))

        if full_price <= 0:
            return 0

        discount = (Decimal("1") - Decimal(str(current_price)) / full_price) * Decimal("100")
        if discount <= 0:
            return 0

        return int(discount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
