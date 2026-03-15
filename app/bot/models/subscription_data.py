from enum import Enum

from aiogram.filters.callback_data import MAX_CALLBACK_LENGTH, CallbackData
from aiogram.filters.callback_data import CallbackDataException

from app.bot.utils.navigation import NavSubscription


class SubscriptionData(CallbackData, prefix="subscription"):
    state: NavSubscription
    is_extend: bool = False
    is_change: bool = False
    user_id: int = 0
    devices: int = 0
    duration: int = 0
    price: float = 0
    plan_code: str = ""
    is_upgrade: bool = False

    @staticmethod
    def _encode_value(key: str, value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, Enum):
            return str(value.value)
        if isinstance(value, bool):
            return str(int(value))
        if isinstance(value, (int, str, float)):
            return str(value)

        raise ValueError(
            f"Attribute {key}={value!r} of type {type(value).__name__!r} "
            f"can not be packed to callback data"
        )

    def pack(self) -> str:
        values = [
            self._encode_value("state", self.state),
            self._encode_value("is_extend", self.is_extend),
            self._encode_value("is_change", self.is_change),
            self._encode_value("user_id", self.user_id),
            self._encode_value("devices", self.devices),
            self._encode_value("duration", self.duration),
            self._encode_value("price", self.price),
        ]

        if self.plan_code or self.is_upgrade:
            values.extend(
                [
                    self._encode_value("plan_code", self.plan_code),
                    self._encode_value("is_upgrade", self.is_upgrade),
                ]
            )

        callback_data = self.__separator__.join((self.__prefix__, *values))
        if len(callback_data.encode()) > MAX_CALLBACK_LENGTH:
            raise ValueError(
                f"Resulted callback data is too long! len({callback_data!r}.encode()) > {MAX_CALLBACK_LENGTH}"
            )
        return callback_data

    @classmethod
    def unpack(cls, value: str) -> "SubscriptionData":
        prefix, *parts = value.split(cls.__separator__)
        names = list(cls.model_fields.keys())

        if prefix != cls.__prefix__:
            raise CallbackDataException(
                f"Bad prefix ({prefix!r} != {cls.__prefix__!r})"
            )

        if len(parts) not in {7, 8, 9}:
            raise TypeError(
                f"Callback data {cls.__name__!r} takes 7, 8 or 9 arguments but {len(parts)} were given"
            )

        payload: dict[str, str] = dict(zip(names[:7], parts[:7]))
        payload.setdefault("plan_code", "")
        payload.setdefault("is_upgrade", "0")

        if len(parts) >= 8:
            payload["plan_code"] = parts[7]
        if len(parts) == 9:
            payload["is_upgrade"] = parts[8]

        return cls(**payload)
