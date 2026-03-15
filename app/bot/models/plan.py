from dataclasses import dataclass
from typing import Any

from app.bot.utils.constants import Currency


@dataclass
class Plan:
    code: str
    devices: int
    prices: dict[str, dict[int, float]]
    title: str | None = None
    is_public: bool = True
    includes_additional_profile: bool = False
    upgrade_from: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Plan":
        devices = data["devices"]
        code = data.get("code") or f"p{devices}"
        return cls(
            code=code,
            devices=devices,
            prices={k: {int(m): p for m, p in v.items()} for k, v in data["prices"].items()},
            title=data.get("title"),
            is_public=data.get("is_public", True),
            includes_additional_profile=data.get("includes_additional_profile", False),
            upgrade_from=data.get("upgrade_from"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "devices": self.devices,
            "prices": {k: {str(m): p for m, p in v.items()} for k, v in self.prices.items()},
            "title": self.title,
            "is_public": self.is_public,
            "includes_additional_profile": self.includes_additional_profile,
            "upgrade_from": self.upgrade_from,
        }

    def get_price(self, currency: Currency | str, duration: int) -> float:
        if isinstance(currency, str):
            currency = Currency.from_code(currency)

        return self.prices[currency.code][duration]
