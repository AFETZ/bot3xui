from __future__ import annotations

import json
import logging
from typing import Any

from aiohttp import web

from app.bot.models import Plan, ServicesContainer, SubscriptionData
from app.bot.payment_gateways import GatewayFactory, PaymentGateway
from app.bot.services.subscription import SubscriptionStatus
from app.bot.utils.constants import Currency
from app.bot.utils.formatting import normalize_price
from app.bot.utils.navigation import NavSubscription
from app.bot.utils.time import get_current_timestamp
from app.config import Config
from app.db.models import User

logger = logging.getLogger(__name__)

NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}
WEB_EXCLUDED_GATEWAYS = {NavSubscription.PAY_TELEGRAM_STARS.value}

GATEWAY_LABELS = {
    NavSubscription.PAY_CRYPTOMUS.value: "Cryptomus",
    NavSubscription.PAY_HELEKET.value: "Heleket",
    NavSubscription.PAY_YOOKASSA.value: "YooKassa",
    NavSubscription.PAY_YOOMONEY.value: "YooMoney",
}

HTML_TEMPLATE = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex,nofollow">
  <title>AFZVPN Кабинет</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --surface: #ffffff;
      --text: #1e242c;
      --muted: #697386;
      --line: #d9e0ea;
      --accent: #087f8c;
      --accent-strong: #075e68;
      --ok: #16794c;
      --warn: #b45309;
      --bad: #b42318;
      --shadow: 0 10px 28px rgba(24, 39, 75, 0.08);
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.45;
    }
    button, select, input { font: inherit; }
    a { color: var(--accent-strong); }
    .shell {
      width: min(1040px, calc(100% - 28px));
      margin: 0 auto;
      padding: 22px 0 42px;
    }
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 26px;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }
    .mark {
      display: inline-grid;
      place-items: center;
      width: 42px;
      height: 42px;
      border-radius: 8px;
      background: #102a2f;
      color: #ffffff;
      font-weight: 800;
    }
    h1, h2, h3, p { margin: 0; }
    h1 { font-size: 22px; line-height: 1.15; }
    h2 { font-size: 18px; margin: 28px 0 12px; }
    h3 { font-size: 16px; margin-bottom: 6px; }
    .subtle { color: var(--muted); font-size: 14px; }
    .pill {
      display: inline-flex;
      align-items: center;
      min-height: 32px;
      padding: 6px 10px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--surface);
      color: var(--muted);
      font-size: 13px;
      white-space: nowrap;
    }
    .pill.active { color: var(--ok); border-color: rgba(22, 121, 76, .25); }
    .pill.expired, .pill.blocked { color: var(--bad); border-color: rgba(180, 35, 24, .25); }
    .pill.unavailable { color: var(--warn); border-color: rgba(180, 83, 9, .25); }
    .status {
      display: grid;
      grid-template-columns: minmax(0, 1.3fr) minmax(260px, .7fr);
      gap: 16px;
      align-items: stretch;
      padding: 18px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    .status-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 14px;
    }
    .metric {
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfd;
      min-width: 0;
    }
    .metric span {
      display: block;
      color: var(--muted);
      font-size: 12px;
    }
    .metric strong {
      display: block;
      margin-top: 4px;
      overflow-wrap: anywhere;
    }
    .actions {
      display: grid;
      gap: 10px;
      align-content: start;
    }
    .button, button {
      min-height: 42px;
      border: 0;
      border-radius: 8px;
      padding: 10px 14px;
      background: var(--accent);
      color: #ffffff;
      cursor: pointer;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      font-weight: 650;
    }
    .button:hover, button:hover { background: var(--accent-strong); }
    .button.secondary, button.secondary {
      background: #edf3f5;
      color: var(--accent-strong);
    }
    .button.secondary:hover, button.secondary:hover { background: #dfecef; }
    button:disabled {
      cursor: wait;
      opacity: .72;
    }
    .section {
      padding: 22px 0 2px;
      border-bottom: 1px solid var(--line);
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
    }
    .option-card {
      display: grid;
      gap: 14px;
      padding: 16px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      min-width: 0;
    }
    .option-card.popular { border-color: rgba(8, 127, 140, .55); }
    .meta {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 8px;
    }
    .tag {
      display: inline-flex;
      align-items: center;
      min-height: 26px;
      padding: 4px 8px;
      border-radius: 999px;
      background: #eef2f6;
      color: #3c4654;
      font-size: 12px;
    }
    form {
      display: grid;
      gap: 10px;
      margin: 0;
    }
    label {
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 13px;
    }
    select {
      width: 100%;
      min-height: 42px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #ffffff;
      color: var(--text);
      padding: 0 10px;
    }
    .notice {
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #ffffff;
      color: var(--muted);
    }
    .notice.bad { border-color: rgba(180, 35, 24, .25); color: var(--bad); }
    .toast {
      position: fixed;
      left: 50%;
      bottom: 20px;
      transform: translateX(-50%);
      min-width: min(360px, calc(100% - 28px));
      padding: 12px 14px;
      border-radius: 8px;
      background: #1e242c;
      color: #ffffff;
      text-align: center;
      box-shadow: var(--shadow);
      opacity: 0;
      pointer-events: none;
      transition: opacity .18s ease;
    }
    .toast.show { opacity: 1; }
    .loading {
      min-height: 280px;
      display: grid;
      place-items: center;
      color: var(--muted);
    }
    @media (max-width: 820px) {
      .status, .grid { grid-template-columns: 1fr; }
      .topbar { align-items: flex-start; }
      .pill { white-space: normal; justify-content: center; text-align: center; }
    }
    @media (max-width: 520px) {
      .shell { width: min(100% - 20px, 1040px); padding-top: 14px; }
      .status-grid { grid-template-columns: 1fr; }
      .topbar { display: grid; }
      h1 { font-size: 20px; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div class="brand">
        <span class="mark">AFZ</span>
        <div>
          <h1>Кабинет AFZVPN</h1>
          <p class="subtle" id="userName"></p>
        </div>
      </div>
      <span class="pill" id="statusPill">Загрузка</span>
    </header>
    <div id="app" class="loading">Загрузка кабинета...</div>
  </main>
  <div class="toast" id="toast"></div>
  <script>
    window.CABINET_API_BASE = __API_BASE__;
  </script>
  <script>
    const apiBase = window.CABINET_API_BASE;
    const app = document.getElementById("app");
    const toast = document.getElementById("toast");
    const statusPill = document.getElementById("statusPill");
    const userName = document.getElementById("userName");
    let state = null;

    const esc = (value) => String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");

    function showToast(message) {
      toast.textContent = message;
      toast.classList.add("show");
      window.setTimeout(() => toast.classList.remove("show"), 2600);
    }

    async function loadState() {
      const response = await fetch(`${apiBase}/state`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(await response.text() || "Не удалось открыть кабинет.");
      }
      state = await response.json();
      render();
    }

    function gatewayOption(gateway, priceInfo) {
      const price = priceInfo ? ` · ${priceInfo.price} ${priceInfo.symbol}` : "";
      return `<option value="${esc(gateway.id)}">${esc(gateway.name)}${esc(price)}</option>`;
    }

    function gatewaySelect(prices) {
      const options = state.gateways
        .filter((gateway) => !prices || prices[gateway.id])
        .map((gateway) => gatewayOption(gateway, prices ? prices[gateway.id] : null))
        .join("");
      if (!options) {
        return `<div class="notice bad">Нет доступных веб-способов оплаты для этого тарифа.</div>`;
      }
      return `<label>Оплата<select name="gateway" required>${options}</select></label>`;
    }

    function durationOptions(plan) {
      return (plan.durations || []).map((duration) => {
        const firstPrice = Object.values(duration.prices || {})[0];
        const suffix = firstPrice ? ` · ${firstPrice.price} ${firstPrice.symbol}` : "";
        const discount = duration.discount_percent ? ` · -${duration.discount_percent}%` : "";
        return `<option value="${duration.days}">${esc(duration.label + suffix + discount)}</option>`;
      }).join("");
    }

    function paymentForm(mode, plan) {
      const durationField = plan.durations && plan.durations.length
        ? `<label>Срок<select name="duration" required>${durationOptions(plan)}</select></label>`
        : "";
      return `
        <form class="pay-form" data-mode="${esc(mode)}" data-plan-code="${esc(plan.code)}">
          ${durationField}
          ${gatewaySelect(null)}
          <button type="submit">Оплатить</button>
        </form>
      `;
    }

    function planCard(plan, mode) {
      const tags = [
        `${plan.devices_label}`,
        plan.includes_additional_profile ? "Обход белых списков" : null,
        plan.is_popular ? "Популярный" : null,
      ].filter(Boolean).map((tag) => `<span class="tag">${esc(tag)}</span>`).join("");
      return `
        <article class="option-card ${plan.is_popular ? "popular" : ""}">
          <div>
            <h3>${esc(plan.title)}</h3>
            <div class="meta">${tags}</div>
          </div>
          ${paymentForm(mode, plan)}
        </article>
      `;
    }

    function quoteCard(quote, mode) {
      const plan = quote.target_plan;
      const tags = [
        plan.devices_label,
        plan.includes_additional_profile ? "Обход белых списков" : null,
      ].filter(Boolean).map((tag) => `<span class="tag">${esc(tag)}</span>`).join("");
      if (quote.price <= 0 && mode === "change") {
        return `
          <article class="option-card">
            <div>
              <h3>${esc(plan.title)}</h3>
              <p class="subtle">Без доплаты, дата окончания не изменится.</p>
              <div class="meta">${tags}</div>
            </div>
            <button type="button" data-apply-change="${esc(plan.code)}">Подтвердить смену</button>
          </article>
        `;
      }
      return `
        <article class="option-card">
          <div>
            <h3>${esc(plan.title)}</h3>
            <p class="subtle">Доплата: ${esc(quote.price)} ${esc(quote.currency_symbol)}. Дата окончания не изменится.</p>
            <div class="meta">${tags}</div>
          </div>
          <form class="pay-form" data-mode="${esc(mode)}" data-plan-code="${esc(plan.code)}">
            ${gatewaySelect(quote.prices)}
            <button type="submit">Оплатить</button>
          </form>
        </article>
      `;
    }

    function statusClass(status) {
      if (status.state === "active") return "active";
      if (status.state === "expired") return "expired";
      if (status.state === "blocked") return "blocked";
      if (status.state === "unavailable") return "unavailable";
      return "";
    }

    function renderStatus() {
      const status = state.status;
      statusPill.className = `pill ${statusClass(status)}`;
      statusPill.textContent = status.label;
      userName.textContent = state.user.name ? state.user.name : "";

      const profileButtons = [
        state.links.primary_profile_url ? `<button class="secondary" type="button" data-copy="${esc(state.links.primary_profile_url)}">Скопировать основную ссылку</button>` : "",
        state.links.additional_profile_url ? `<button class="secondary" type="button" data-copy="${esc(state.links.additional_profile_url)}">Скопировать ссылку БС</button>` : "",
      ].join("");

      return `
        <section class="status">
          <div>
            <h2>Статус подписки</h2>
            <p class="subtle">${esc(status.message)}</p>
            <div class="status-grid">
              <div class="metric"><span>Тариф</span><strong>${esc(status.plan_title || "-")}</strong></div>
              <div class="metric"><span>Активна до</span><strong>${esc(status.expiry_date || "-")}</strong></div>
              <div class="metric"><span>Устройства</span><strong>${esc(status.devices_label || "-")}</strong></div>
              <div class="metric"><span>Доп. профиль</span><strong>${status.has_additional_profile ? "Подключен" : "Не подключен"}</strong></div>
            </div>
          </div>
          <div class="actions">
            ${profileButtons || `<div class="notice">Ссылки появятся после оплаты и активации.</div>`}
            <a class="button secondary" href="${esc(state.cabinet_url)}">Обновить кабинет</a>
          </div>
        </section>
      `;
    }

    function renderPaymentsNotice() {
      if (state.gateways.length) return "";
      return `<section class="section"><div class="notice bad">Для веб-кабинета нужен внешний платежный метод: YooKassa, YooMoney, Cryptomus или Heleket.</div></section>`;
    }

    function renderPurchase() {
      if (!state.purchase.plans.length || state.status.state === "blocked" || state.status.state === "unavailable") return "";
      return `
        <section class="section">
          <h2>${state.status.state === "active" ? "Новая покупка" : "Восстановить доступ"}</h2>
          <div class="grid">${state.purchase.plans.map((plan) => planCard(plan, "purchase")).join("")}</div>
        </section>
      `;
    }

    function renderRenew() {
      if (!state.renew || state.status.state !== "active") return "";
      return `
        <section class="section">
          <h2>Продлить текущий тариф</h2>
          <div class="grid">${planCard(state.renew.plan, "extend")}</div>
        </section>
      `;
    }

    function renderUpgrade() {
      if (!state.upgrade || state.status.state !== "active") return "";
      return `
        <section class="section">
          <h2>Подключить обход белых списков</h2>
          <div class="grid">${quoteCard(state.upgrade, "upgrade")}</div>
        </section>
      `;
    }

    function renderChange() {
      if (!state.change || !state.change.quotes.length || state.status.state !== "active") return "";
      return `
        <section class="section">
          <h2>Сменить тариф</h2>
          <div class="grid">${state.change.quotes.map((quote) => quoteCard(quote, "change")).join("")}</div>
        </section>
      `;
    }

    function render() {
      app.className = "";
      app.innerHTML = [
        renderStatus(),
        renderPaymentsNotice(),
        state.status.state === "active" ? renderRenew() : renderPurchase(),
        renderUpgrade(),
        renderChange(),
      ].join("");
      bindActions();
    }

    function bindActions() {
      document.querySelectorAll("[data-copy]").forEach((button) => {
        button.addEventListener("click", async () => {
          const value = button.getAttribute("data-copy");
          try {
            await navigator.clipboard.writeText(value);
            showToast("Ссылка скопирована.");
          } catch {
            showToast(value);
          }
        });
      });

      document.querySelectorAll(".pay-form").forEach((form) => {
        form.addEventListener("submit", async (event) => {
          event.preventDefault();
          const button = form.querySelector("button[type=submit]");
          const formData = new FormData(form);
          const payload = {
            mode: form.dataset.mode,
            plan_code: form.dataset.planCode,
            duration: formData.get("duration"),
            gateway: formData.get("gateway"),
          };
          button.disabled = true;
          try {
            const response = await fetch(`${apiBase}/pay`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(payload),
            });
            if (!response.ok) throw new Error(await response.text() || "Не удалось создать оплату.");
            const data = await response.json();
            window.location.href = data.pay_url;
          } catch (error) {
            showToast(error.message || "Ошибка оплаты.");
          } finally {
            button.disabled = false;
          }
        });
      });

      document.querySelectorAll("[data-apply-change]").forEach((button) => {
        button.addEventListener("click", async () => {
          button.disabled = true;
          try {
            const response = await fetch(`${apiBase}/change/apply`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ plan_code: button.getAttribute("data-apply-change") }),
            });
            if (!response.ok) throw new Error(await response.text() || "Не удалось сменить тариф.");
            showToast("Тариф изменен.");
            await loadState();
          } catch (error) {
            showToast(error.message || "Ошибка смены тарифа.");
          } finally {
            button.disabled = false;
          }
        });
      });
    }

    loadState().catch((error) => {
      app.className = "";
      statusPill.textContent = "Ошибка";
      app.innerHTML = `<div class="notice bad">${esc(error.message)}</div>`;
    });
  </script>
</body>
</html>
"""


def _enum_value(value: object) -> str:
    return getattr(value, "value", str(value))


def _duration_label(days: int) -> str:
    if days == 365:
        return "1 год"
    if days > 0 and days % 365 == 0:
        years = days // 365
        return f"{years} года" if years in {2, 3, 4} else f"{years} лет"
    if days == 30:
        return "1 месяц"
    if days > 0 and days % 30 == 0:
        months = days // 30
        if months in {2, 3, 4}:
            return f"{months} месяца"
        return f"{months} месяцев"
    if days % 10 == 1 and days % 100 != 11:
        return f"{days} день"
    if days % 10 in {2, 3, 4} and days % 100 not in {12, 13, 14}:
        return f"{days} дня"
    return f"{days} дней"


def _device_label(devices: int | None) -> str:
    if devices is None:
        return ""
    if devices == -1:
        return "Безлимит устройств"
    if devices == 1:
        return "1 устройство"
    if devices in {2, 3, 4}:
        return f"{devices} устройства"
    return f"{devices} устройств"


def _remaining_days(status: SubscriptionStatus) -> int | None:
    if status.expiry_timestamp is None:
        return None
    remaining_ms = max(status.expiry_timestamp - get_current_timestamp(), 0)
    if remaining_ms <= 0:
        return 0
    return max(1, int((remaining_ms + 86_399_999) // 86_400_000))


class CabinetWeb:
    def __init__(
        self,
        *,
        config: Config,
        services: ServicesContainer,
        gateway_factory: GatewayFactory,
    ) -> None:
        self.config = config
        self.services = services
        self.gateway_factory = gateway_factory

    def _cabinet_url(self, user: User) -> str:
        return self.services.subscription.get_cabinet_url(user)

    def _web_gateways(self) -> list[PaymentGateway]:
        return [
            gateway
            for gateway in self.gateway_factory.get_gateways()
            if _enum_value(gateway.callback) not in WEB_EXCLUDED_GATEWAYS
        ]

    def _gateway_payload(self, gateway: PaymentGateway) -> dict[str, Any]:
        callback = _enum_value(gateway.callback)
        return {
            "id": callback,
            "name": GATEWAY_LABELS.get(callback, str(gateway.name)),
            "currency": gateway.currency.code,
            "symbol": gateway.currency.symbol,
        }

    def _price_for_plan(
        self,
        plan: Plan,
        gateway: PaymentGateway,
        duration: int,
    ) -> float | int | None:
        try:
            return plan.get_price(currency=gateway.currency, duration=duration)
        except (KeyError, ValueError):
            return None

    def _plan_payload(
        self,
        plan: Plan,
        gateways: list[PaymentGateway],
    ) -> dict[str, Any]:
        durations = []
        for duration in plan.get_available_durations(self.services.plan.get_durations()):
            prices = {}
            for gateway in gateways:
                price = self._price_for_plan(plan, gateway, duration)
                if price is None:
                    continue
                prices[_enum_value(gateway.callback)] = {
                    "price": price,
                    "currency": gateway.currency.code,
                    "symbol": gateway.currency.symbol,
                }
            if not prices:
                continue

            try:
                discount_percent = plan.get_discount_percent(
                    currency=Currency.from_code(self.config.shop.CURRENCY),
                    duration=duration,
                )
            except (KeyError, ValueError):
                discount_percent = 0

            durations.append(
                {
                    "days": duration,
                    "label": _duration_label(duration),
                    "discount_percent": discount_percent,
                    "prices": prices,
                }
            )

        return {
            "code": plan.code,
            "title": plan.title or _device_label(plan.devices),
            "devices": plan.devices,
            "devices_label": _device_label(plan.devices),
            "includes_additional_profile": plan.includes_additional_profile,
            "is_popular": plan.is_popular,
            "durations": durations,
        }

    def _status_payload(
        self,
        user: User,
        status: SubscriptionStatus,
    ) -> dict[str, Any]:
        plan = status.plan
        devices = status.client_data.max_devices_count if status.client_data else None
        remaining_days = _remaining_days(status)

        if getattr(user, "is_blocked", False):
            state = "blocked"
            label = "Заблокирована"
            message = "Доступ к подписке ограничен. Оплата в кабинете недоступна."
        elif not status.status_check_ok:
            state = "unavailable"
            label = "Проверка недоступна"
            message = "Не получилось проверить подписку в панели. Попробуйте обновить страницу позже."
        elif status.is_active:
            state = "active"
            label = "Активна"
            message = (
                f"Осталось: {_duration_label(remaining_days)}."
                if remaining_days is not None
                else "Подписка активна."
            )
        elif status.client_data and status.client_data.has_subscription_expired:
            state = "expired"
            label = "Закончилась"
            message = "Оплатите тариф, и старая ссылка снова начнет работать."
        else:
            state = "not_active"
            label = "Не активна"
            message = "Выберите тариф и оплатите подключение."

        return {
            "state": state,
            "label": label,
            "message": message,
            "plan_code": plan.code if plan else "",
            "plan_title": plan.title if plan and plan.title else _device_label(devices),
            "expiry_date": status.expiry_date,
            "remaining_days": remaining_days,
            "devices": devices,
            "devices_label": _device_label(devices),
            "has_additional_profile": status.has_additional_profile,
        }

    async def _quote_prices(
        self,
        *,
        user: User,
        target_plan: Plan | None = None,
    ) -> dict[str, dict[str, Any]]:
        prices = {}
        for gateway in self._web_gateways():
            quote = await self.services.subscription.get_upgrade_quote(
                user=user,
                currency=gateway.currency,
                target_plan=target_plan,
            )
            if not quote:
                continue

            price = self.services.subscription.apply_personal_discount(
                user=user,
                price=quote.price,
                currency=gateway.currency,
            )
            prices[_enum_value(gateway.callback)] = {
                "price": price,
                "currency": gateway.currency.code,
                "symbol": gateway.currency.symbol,
            }
        return prices

    async def _quote_payload(
        self,
        *,
        user: User,
        quote,
        currency: Currency,
    ) -> dict[str, Any]:
        price = self.services.subscription.apply_personal_discount(
            user=user,
            price=quote.price,
            currency=currency,
        )
        return {
            "target_plan": self._plan_payload(quote.target_plan, self._web_gateways()),
            "price": price,
            "currency": currency.code,
            "currency_symbol": currency.symbol,
            "renewal_price": quote.renewal_price,
            "renewal_duration_days": quote.renewal_duration_days,
            "expiry_date": quote.expiry_date,
            "prices": await self._quote_prices(user=user, target_plan=quote.target_plan),
        }

    async def _resolve_user_status(
        self,
        request: web.Request,
    ) -> tuple[User, SubscriptionStatus]:
        vpn_id = request.match_info["vpn_id"]
        user, status = await self.services.subscription.get_subscription_status_by_vpn_id(
            vpn_id
        )
        if not user or not status:
            raise web.HTTPNotFound(text="Кабинет не найден.")
        return user, status

    async def page(self, request: web.Request) -> web.Response:
        api_base = json.dumps(f"/cabinet/{request.match_info['vpn_id']}/api")
        html = HTML_TEMPLATE.replace("__API_BASE__", api_base)
        return web.Response(
            text=html,
            content_type="text/html",
            charset="utf-8",
            headers={
                **NO_STORE_HEADERS,
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
            },
        )

    async def state(self, request: web.Request) -> web.Response:
        user, status = await self._resolve_user_status(request)
        gateways = self._web_gateways()
        shop_currency = Currency.from_code(self.config.shop.CURRENCY)

        purchase_plans = []
        if not status.is_active and not getattr(user, "is_blocked", False):
            purchase_plans = [
                self._plan_payload(plan, gateways)
                for plan in self.services.plan.get_all_plans(
                    prefer_additional_profile=not user.server_id
                    and not user.current_plan_code,
                )
            ]
            purchase_plans = [plan for plan in purchase_plans if plan["durations"]]

        renew = None
        if status.is_active and status.plan:
            renew_plan = status.plan
            renew_payload = self._plan_payload(renew_plan, gateways)
            if renew_payload["durations"]:
                renew = {"plan": renew_payload}

        change = None
        if status.is_active:
            quotes = await self.services.subscription.get_plan_change_quotes(
                user=user,
                currency=shop_currency,
            )
            quote_payloads = [
                await self._quote_payload(
                    user=user,
                    quote=quote,
                    currency=shop_currency,
                )
                for quote in quotes
            ]
            change = {"quotes": quote_payloads}

        upgrade = None
        if status.is_active and self.services.subscription.can_upgrade_plan(status):
            quote = await self.services.subscription.get_upgrade_quote(
                user=user,
                currency=shop_currency,
            )
            if quote:
                upgrade = await self._quote_payload(
                    user=user,
                    quote=quote,
                    currency=shop_currency,
                )

        primary_profile_url = await self.services.vpn.get_key(user)
        additional_profile_url = (
            self.services.subscription.get_additional_profile_url(user)
            if status.has_additional_profile
            else None
        )

        return web.json_response(
            {
                "cabinet_url": self._cabinet_url(user),
                "user": {"name": user.first_name},
                "status": self._status_payload(user, status),
                "links": {
                    "primary_profile_url": primary_profile_url,
                    "additional_profile_url": additional_profile_url,
                },
                "gateways": [self._gateway_payload(gateway) for gateway in gateways],
                "purchase": {"plans": purchase_plans},
                "renew": renew,
                "upgrade": upgrade,
                "change": change,
            },
            headers=NO_STORE_HEADERS,
        )

    async def _read_json(self, request: web.Request) -> dict[str, Any]:
        try:
            payload = await request.json()
        except ValueError as exception:
            raise web.HTTPBadRequest(text="Некорректный запрос.") from exception

        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="Некорректный запрос.")
        return payload

    def _get_web_gateway(self, gateway_id: str) -> PaymentGateway:
        gateway_ids = {_enum_value(gateway.callback) for gateway in self._web_gateways()}
        if gateway_id not in gateway_ids:
            raise web.HTTPBadRequest(text="Этот способ оплаты недоступен в кабинете.")

        try:
            return self.gateway_factory.get_gateway(gateway_id)
        except ValueError as exception:
            raise web.HTTPBadRequest(text="Этот способ оплаты недоступен.") from exception

    def _get_plan(self, plan_code: str | None, devices: int = 0) -> Plan:
        plan = self.services.subscription.get_payment_plan(
            plan_code=plan_code,
            devices=devices,
        )
        if not plan:
            raise web.HTTPBadRequest(text="Тариф не найден.")
        return plan

    def _get_duration(self, payload: dict[str, Any], plan: Plan) -> int:
        try:
            duration = int(payload.get("duration") or 0)
        except (TypeError, ValueError) as exception:
            raise web.HTTPBadRequest(text="Срок тарифа не выбран.") from exception

        available_durations = plan.get_available_durations(self.services.plan.get_durations())
        if duration not in available_durations:
            raise web.HTTPBadRequest(text="Этот срок недоступен для тарифа.")
        return duration

    def _payment_state(self, gateway: PaymentGateway) -> NavSubscription:
        return NavSubscription(_enum_value(gateway.callback))

    async def _build_payment_data(
        self,
        *,
        user: User,
        status: SubscriptionStatus,
        payload: dict[str, Any],
        gateway: PaymentGateway,
    ) -> SubscriptionData:
        mode = str(payload.get("mode") or "purchase")
        plan_code = str(payload.get("plan_code") or "")

        if mode == "extend" and not status.is_active:
            mode = "purchase"

        if mode == "purchase":
            if status.is_active:
                raise web.HTTPBadRequest(text="Для активной подписки используйте продление.")
            plan = self._get_plan(plan_code)
            duration = self._get_duration(payload, plan)
            price = self._price_for_plan(plan, gateway, duration)
            if price is None:
                raise web.HTTPBadRequest(text="Этот способ оплаты недоступен для тарифа.")
            price = self.services.subscription.apply_personal_discount(
                user=user,
                price=price,
                currency=gateway.currency,
            )
            return SubscriptionData(
                state=self._payment_state(gateway),
                user_id=user.tg_id,
                devices=plan.devices,
                duration=duration,
                price=price,
                plan_code=plan.code,
            )

        if mode == "extend":
            if not status.is_active:
                raise web.HTTPBadRequest(text="Подписка не активна.")
            plan = status.plan or self._get_plan(plan_code)
            duration = self._get_duration(payload, plan)
            price = self._price_for_plan(plan, gateway, duration)
            if price is None:
                raise web.HTTPBadRequest(text="Этот способ оплаты недоступен для тарифа.")
            price = self.services.subscription.apply_personal_discount(
                user=user,
                price=price,
                currency=gateway.currency,
            )
            return SubscriptionData(
                state=self._payment_state(gateway),
                is_extend=True,
                user_id=user.tg_id,
                devices=plan.devices,
                duration=duration,
                price=price,
                plan_code=plan.code,
            )

        if mode == "change":
            if not status.is_active:
                raise web.HTTPBadRequest(text="Смена тарифа доступна только активной подписке.")
            target_plan = self.services.plan.get_plan_by_code(plan_code)
            if not target_plan:
                raise web.HTTPBadRequest(text="Тариф не найден.")
            quote = await self.services.subscription.get_upgrade_quote(
                user=user,
                currency=gateway.currency,
                target_plan=target_plan,
            )
            if not quote:
                raise web.HTTPBadRequest(text="Смена тарифа сейчас недоступна.")
            price = self.services.subscription.apply_personal_discount(
                user=user,
                price=quote.price,
                currency=gateway.currency,
            )
            if price <= 0:
                raise web.HTTPBadRequest(text="Этот переход не требует оплаты.")
            return SubscriptionData(
                state=self._payment_state(gateway),
                is_change=True,
                user_id=user.tg_id,
                devices=target_plan.devices,
                duration=quote.renewal_duration_days,
                price=price,
                plan_code=target_plan.code,
            )

        if mode == "upgrade":
            if not status.is_active:
                raise web.HTTPBadRequest(text="Опция доступна только активной подписке.")
            quote = await self.services.subscription.get_upgrade_quote(
                user=user,
                currency=gateway.currency,
            )
            if not quote:
                raise web.HTTPBadRequest(text="Подключение опции сейчас недоступно.")
            price = self.services.subscription.apply_personal_discount(
                user=user,
                price=quote.price,
                currency=gateway.currency,
            )
            if price <= 0:
                raise web.HTTPBadRequest(text="Этот переход не требует оплаты.")
            return SubscriptionData(
                state=self._payment_state(gateway),
                is_upgrade=True,
                user_id=user.tg_id,
                devices=quote.target_plan.devices,
                duration=quote.renewal_duration_days,
                price=price,
                plan_code=quote.target_plan.code,
            )

        raise web.HTTPBadRequest(text="Неизвестное действие.")

    async def pay(self, request: web.Request) -> web.Response:
        user, status = await self._resolve_user_status(request)
        if getattr(user, "is_blocked", False):
            raise web.HTTPForbidden(text="Оплата недоступна.")
        if not status.status_check_ok:
            raise web.HTTPServiceUnavailable(text="Проверка подписки временно недоступна.")

        payload = await self._read_json(request)
        gateway_id = str(payload.get("gateway") or "")
        gateway = self._get_web_gateway(gateway_id)
        data = await self._build_payment_data(
            user=user,
            status=status,
            payload=payload,
            gateway=gateway,
        )

        pay_url = await gateway.create_payment(
            data,
            return_url=self._cabinet_url(user),
        )
        logger.info(
            "Web cabinet payment link created for user %s mode=%s gateway=%s.",
            user.tg_id,
            payload.get("mode"),
            gateway_id,
        )
        return web.json_response({"pay_url": pay_url}, headers=NO_STORE_HEADERS)

    async def apply_change(self, request: web.Request) -> web.Response:
        user, status = await self._resolve_user_status(request)
        if getattr(user, "is_blocked", False):
            raise web.HTTPForbidden(text="Смена тарифа недоступна.")
        if not status.status_check_ok or not status.is_active:
            raise web.HTTPBadRequest(text="Смена тарифа доступна только активной подписке.")

        payload = await self._read_json(request)
        plan_code = str(payload.get("plan_code") or "")
        target_plan = self.services.plan.get_plan_by_code(plan_code)
        if not target_plan:
            raise web.HTTPBadRequest(text="Тариф не найден.")

        quote = await self.services.subscription.get_upgrade_quote(
            user=user,
            currency=Currency.from_code(self.config.shop.CURRENCY),
            target_plan=target_plan,
        )
        if not quote or normalize_price(quote.price, self.config.shop.CURRENCY) != 0:
            raise web.HTTPBadRequest(text="Этот переход требует оплаты.")

        success = await self.services.vpn.change_subscription(
            user=user,
            devices=target_plan.devices,
        )
        if not success:
            raise web.HTTPBadRequest(text="Не удалось сменить тариф.")

        await self.services.subscription.update_current_plan(
            user=user,
            plan_code=target_plan.code,
            refresh_period=False,
        )
        logger.info(
            "Web cabinet applied free plan change for user %s to plan %s.",
            user.tg_id,
            target_plan.code,
        )
        return web.json_response({"ok": True}, headers=NO_STORE_HEADERS)


def setup_cabinet_routes(
    app: web.Application,
    *,
    config: Config,
    services: ServicesContainer,
    gateway_factory: GatewayFactory,
) -> None:
    cabinet = CabinetWeb(
        config=config,
        services=services,
        gateway_factory=gateway_factory,
    )
    app.router.add_get("/cabinet/{vpn_id}", cabinet.page)
    app.router.add_get("/cabinet/{vpn_id}/api/state", cabinet.state)
    app.router.add_post("/cabinet/{vpn_id}/api/pay", cabinet.pay)
    app.router.add_post("/cabinet/{vpn_id}/api/change/apply", cabinet.apply_change)
