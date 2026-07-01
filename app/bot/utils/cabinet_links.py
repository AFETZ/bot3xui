from __future__ import annotations

from typing import Any


def normalize_base_url(domain: str | None) -> str | None:
    if not domain:
        return None

    value = str(domain).strip().rstrip("/")
    if not value:
        return None
    if value.startswith(("http://", "https://")):
        return value
    return f"https://{value}"


def _bot_config(config: Any) -> Any:
    return getattr(config, "bot", config)


def public_base_url(config: Any) -> str | None:
    return normalize_base_url(getattr(_bot_config(config), "DOMAIN", None))


def cabinet_base_url(config: Any) -> str | None:
    bot_config = _bot_config(config)
    return normalize_base_url(
        getattr(bot_config, "CABINET_DOMAIN", None)
        or getattr(bot_config, "DOMAIN", None)
    )


def cabinet_url_for_user(config: Any, user: Any) -> str | None:
    vpn_id = getattr(user, "vpn_id", None)
    base_url = cabinet_base_url(config)
    if not vpn_id or not base_url:
        return None
    return f"{base_url}/cabinet/{vpn_id}"


def cabinet_save_hint(
    cabinet_url: str | None,
    *,
    language_code: str | None = None,
    context: str = "payment",
) -> str:
    if not cabinet_url:
        return ""

    if language_code == "en":
        if context == "renewal":
            return (
                "\n\n🌐 Backup renewal link: save this cabinet page now. "
                "It works without Telegram, the bot, or an active VPN:\n"
                f"{cabinet_url}"
            )
        return (
            "\n\n🌐 Save your personal cabinet for renewal without Telegram, "
            "the bot, or an active VPN:\n"
            f"{cabinet_url}"
        )

    if context == "renewal":
        return (
            "\n\n🌐 Запасной способ продления: сохраните личный кабинет заранее. "
            "Он работает без Telegram, бота и активного VPN:\n"
            f"{cabinet_url}"
        )

    return (
        "\n\n🌐 Сохраните личный кабинет для продления без Telegram, "
        "бота и активного VPN:\n"
        f"{cabinet_url}"
    )


def cabinet_renewal_hint(config: Any, user: Any) -> str:
    return cabinet_save_hint(
        cabinet_url_for_user(config, user),
        language_code=getattr(user, "language_code", None),
        context="renewal",
    )
