from types import SimpleNamespace

from app.bot.utils.cabinet_links import (
    cabinet_base_url,
    cabinet_renewal_hint,
    cabinet_save_hint,
    cabinet_url_for_user,
    normalize_base_url,
    public_base_url,
)


def test_normalize_base_url_adds_https_and_trims_slash():
    assert normalize_base_url("cabinet.example/") == "https://cabinet.example"
    assert normalize_base_url(" https://cabinet.example/path/ ") == "https://cabinet.example/path"
    assert normalize_base_url(None) is None


def test_public_and_cabinet_base_urls_use_expected_domains():
    config = SimpleNamespace(
        bot=SimpleNamespace(
            DOMAIN="bot.example/",
            CABINET_DOMAIN="https://pay.example/",
        )
    )

    assert public_base_url(config) == "https://bot.example"
    assert cabinet_base_url(config) == "https://pay.example"


def test_cabinet_url_falls_back_to_public_domain():
    config = SimpleNamespace(
        bot=SimpleNamespace(
            DOMAIN="bot.example",
            CABINET_DOMAIN=None,
        )
    )
    user = SimpleNamespace(vpn_id="vpn-1")

    assert cabinet_url_for_user(config, user) == "https://bot.example/cabinet/vpn-1"


def test_cabinet_url_returns_none_without_vpn_id_or_domain():
    config = SimpleNamespace(bot=SimpleNamespace(DOMAIN=None))

    assert cabinet_url_for_user(config, SimpleNamespace()) is None


def test_cabinet_save_hint_supports_payment_and_renewal_contexts():
    url = "https://pay.example/cabinet/vpn-1"

    assert "Сохраните личный кабинет" in cabinet_save_hint(url)
    assert "Запасной способ продления" in cabinet_save_hint(url, context="renewal")
    assert "Backup renewal link" in cabinet_save_hint(
        url,
        language_code="en",
        context="renewal",
    )


def test_cabinet_renewal_hint_builds_localized_user_link():
    config = SimpleNamespace(
        bot=SimpleNamespace(
            DOMAIN="bot.example",
            CABINET_DOMAIN="pay.example",
        )
    )
    user = SimpleNamespace(vpn_id="vpn-2", language_code="en")

    assert cabinet_renewal_hint(config, user) == (
        "\n\n🌐 Backup renewal link: save this cabinet page now. "
        "It works without Telegram, the bot, or an active VPN:\n"
        "https://pay.example/cabinet/vpn-2"
    )
