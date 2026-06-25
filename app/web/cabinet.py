from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import time
import uuid
from typing import Any

from aiohttp import web

from app.bot.models import Plan, ServicesContainer, SubscriptionData
from app.bot.payment_gateways import GatewayFactory, PaymentGateway
from app.bot.services.subscription import SubscriptionStatus
from app.bot.utils.constants import Currency
from app.bot.utils.formatting import normalize_price
from app.bot.utils.navigation import NavSubscription
from app.bot.utils.time import get_current_timestamp
from app.config import BASE_DIR, Config
from app.db.models import User

logger = logging.getLogger(__name__)

NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}
WEB_EXCLUDED_GATEWAYS = {NavSubscription.PAY_TELEGRAM_STARS.value}
WEB_USER_FIRST_NAME = "Web"
WEB_USER_LANGUAGE = "ru"
WEB_USER_TG_ID_MIN = 100_000_000
WEB_USER_TG_ID_RANGE = 900_000_000
ACCOUNT_COOKIE_NAME = "afzvpn_account"
ACCOUNT_SESSION_TTL_SECONDS = 60 * 60 * 24 * 30
PASSWORD_HASH_ITERATIONS = 310_000
LOGIN_PATTERN = re.compile(r"^[A-Za-z0-9_.@+-]{3,128}$")

GATEWAY_LABELS = {
    NavSubscription.PAY_CRYPTOMUS.value: "Cryptomus",
    NavSubscription.PAY_HELEKET.value: "Heleket",
    NavSubscription.PAY_YOOKASSA.value: "YooKassa",
    NavSubscription.PAY_YOOMONEY.value: "YooMoney",
}
VPN_ID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)

PUBLIC_TEMPLATE = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex,nofollow">
  <title>AFZVPN</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f7f8;
      --ink: #172026;
      --muted: #657180;
      --surface: #ffffff;
      --line: #d7e0e5;
      --accent: #087f8c;
      --accent-dark: #075e68;
      --soft: #e8f2f3;
      --bad: #b42318;
      --shadow: 0 18px 46px rgba(18, 35, 44, .13);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.45;
    }
    button, input, select { font: inherit; }
    .page {
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr auto;
    }
    .topbar {
      width: min(1120px, calc(100% - 32px));
      margin: 0 auto;
      padding: 18px 0;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }
    .brand {
      display: inline-flex;
      align-items: center;
      gap: 12px;
      font-weight: 800;
      letter-spacing: 0;
    }
    .mark {
      display: grid;
      place-items: center;
      width: 42px;
      height: 42px;
      border-radius: 8px;
      background: #102a2f;
      color: #fff;
      font-weight: 900;
    }
    .support {
      color: var(--accent-dark);
      text-decoration: none;
      font-weight: 650;
    }
    .hero {
      width: min(1120px, calc(100% - 32px));
      margin: 0 auto 34px;
      min-height: 620px;
      display: grid;
      grid-template-columns: minmax(0, 1.05fr) minmax(360px, .95fr);
      gap: 28px;
      align-items: start;
    }
    .intro {
      position: relative;
      overflow: hidden;
      border-radius: 8px;
      min-height: 620px;
      height: min(680px, calc(100vh - 110px));
      padding: 34px;
      display: grid;
      align-content: end;
      color: #fff;
      background:
        linear-gradient(180deg, rgba(9, 25, 31, .12), rgba(9, 25, 31, .82)),
        url("/assets/start_banner.jpg") center / cover no-repeat,
        #163138;
      box-shadow: var(--shadow);
    }
    h1, h2, h3, p { margin: 0; }
    h1 {
      max-width: 700px;
      font-size: clamp(38px, 6vw, 72px);
      line-height: .98;
      letter-spacing: 0;
    }
    .lead {
      max-width: 610px;
      margin-top: 18px;
      color: rgba(255, 255, 255, .88);
      font-size: 18px;
    }
    .login-panel {
      align-self: start;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 24px;
      box-shadow: var(--shadow);
    }
    .login-panel h2 { font-size: 24px; line-height: 1.15; }
    .hint {
      margin-top: 8px;
      color: var(--muted);
      font-size: 15px;
    }
    .mode-switch {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
      margin-top: 18px;
      padding: 4px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #eef3f5;
    }
    .mode-switch button {
      min-height: 40px;
      background: transparent;
      color: var(--muted);
      font-weight: 750;
    }
    .mode-switch button.active {
      background: var(--surface);
      color: var(--accent-dark);
      box-shadow: 0 5px 14px rgba(18, 35, 44, .08);
    }
    .view { margin-top: 20px; }
    .view.hidden { display: none; }
    .plans-list {
      display: grid;
      gap: 10px;
      margin-top: 12px;
    }
    .plan-card {
      display: grid;
      gap: 12px;
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfd;
    }
    .plan-card.popular { border-color: rgba(8, 127, 140, .55); }
    .plan-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
    }
    .plan-head h3 { font-size: 16px; margin: 0; }
    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 3px 8px;
      border-radius: 999px;
      background: var(--soft);
      color: var(--accent-dark);
      font-size: 12px;
      font-weight: 700;
      white-space: nowrap;
    }
    .plan-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 7px;
      color: var(--muted);
      font-size: 13px;
    }
    form {
      display: grid;
      gap: 12px;
      margin-top: 22px;
    }
    label {
      display: grid;
      gap: 7px;
      color: var(--muted);
      font-size: 13px;
    }
    input {
      width: 100%;
      min-height: 48px;
      padding: 0 13px;
      border: 1px solid var(--line);
      border-radius: 8px;
      color: var(--ink);
      background: #fbfcfd;
    }
    select {
      width: 100%;
      min-height: 42px;
      padding: 0 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      color: var(--ink);
      background: #fff;
    }
    input:focus {
      outline: 3px solid rgba(8, 127, 140, .17);
      border-color: var(--accent);
    }
    select:focus {
      outline: 3px solid rgba(8, 127, 140, .17);
      border-color: var(--accent);
    }
    button {
      min-height: 48px;
      border: 0;
      border-radius: 8px;
      background: var(--accent);
      color: #fff;
      font-weight: 760;
      cursor: pointer;
    }
    button:hover { background: var(--accent-dark); }
    button:disabled { opacity: .72; cursor: wait; }
    .error {
      display: none;
      color: var(--bad);
      border: 1px solid rgba(180, 35, 24, .22);
      background: #fff7f6;
      border-radius: 8px;
      padding: 11px 12px;
      font-size: 14px;
    }
    .error.show { display: block; }
    .message {
      display: none;
      margin-top: 14px;
      color: var(--accent-dark);
      border: 1px solid rgba(8, 127, 140, .22);
      background: #f2fbfb;
      border-radius: 8px;
      padding: 11px 12px;
      font-size: 14px;
    }
    .message.show { display: block; }
    .message a {
      color: var(--accent-dark);
      font-weight: 750;
    }
    .form-actions {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
      align-items: center;
    }
    .secondary {
      background: #e8f2f3;
      color: var(--accent-dark);
    }
    .secondary:hover {
      background: #d8e9eb;
    }
    .link-button {
      min-height: 0;
      padding: 0;
      background: transparent;
      color: var(--accent-dark);
      font-weight: 750;
      text-decoration: underline;
    }
    .link-button:hover {
      background: transparent;
      color: var(--accent);
    }
    .tiles {
      margin-top: 18px;
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }
    .tile {
      min-height: 92px;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfd;
    }
    .tile strong {
      display: block;
      font-size: 14px;
      margin-bottom: 4px;
    }
    .tile span {
      color: var(--muted);
      font-size: 12px;
    }
    .steps {
      width: min(1120px, calc(100% - 32px));
      margin: 0 auto 40px;
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
    }
    .step {
      padding: 18px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    .step span {
      display: inline-grid;
      place-items: center;
      width: 32px;
      height: 32px;
      margin-bottom: 12px;
      border-radius: 8px;
      background: var(--soft);
      color: var(--accent-dark);
      font-weight: 800;
    }
    .step h3 { font-size: 16px; margin-bottom: 6px; }
    .step p { color: var(--muted); font-size: 14px; }
    footer {
      width: min(1120px, calc(100% - 32px));
      margin: 0 auto;
      padding: 0 0 22px;
      color: var(--muted);
      font-size: 13px;
    }
    @media (max-width: 900px) {
      .hero { grid-template-columns: 1fr; min-height: 0; }
      .intro { min-height: 420px; height: auto; }
      .steps { grid-template-columns: 1fr; }
    }
    @media (max-width: 560px) {
      .topbar { width: min(100% - 20px, 1120px); }
      .hero, .steps, footer { width: min(100% - 20px, 1120px); }
      .intro { min-height: 360px; padding: 22px; }
      .login-panel { padding: 18px; }
      .mode-switch { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .form-actions { grid-template-columns: 1fr; }
      .tiles { grid-template-columns: 1fr; }
      .support { font-size: 14px; }
    }
  </style>
</head>
<body>
  <div class="page">
    <header class="topbar">
      <div class="brand"><span class="mark">AFZ</span><span>AFZVPN</span></div>
      <span class="support">Оплата и продление</span>
    </header>
    <main>
      <section class="hero">
        <div class="intro">
          <div>
            <h1>Личный кабинет для оплаты&nbsp;и продления VPN</h1>
            <p class="lead">Откройте кабинет по своей ссылке подписки, продлите тариф, оплатите доступ и скопируйте ссылки профилей без ожидания ответа в Telegram.</p>
          </div>
        </div>
        <div class="login-panel">
          <h2>Купить или войти</h2>
          <p class="hint">Новый пользователь может оплатить VPN прямо здесь. Если подписка уже есть, вставьте старую ссылку и откройте свой кабинет.</p>
          <div class="message" id="accountBanner"></div>
          <div class="mode-switch">
            <button class="active" type="button" data-mode="new">Купить VPN</button>
            <button type="button" data-mode="login">Войти</button>
            <button type="button" data-mode="register">Регистрация</button>
            <button type="button" data-mode="existing">Уже есть ссылка</button>
          </div>
          <div class="view" id="newUserView">
            <p class="hint">Выберите тариф, срок и способ оплаты. После оплаты откроется ваш новый кабинет со ссылкой подключения.</p>
            <div class="plans-list" id="plansList">Загрузка тарифов...</div>
            <div class="error" id="newUserError"></div>
          </div>
          <div class="view hidden" id="loginView">
            <form id="loginAccountForm">
              <label>
                Логин или email
                <input id="loginAccountValue" name="login" autocomplete="username" placeholder="client@example.com" required>
              </label>
              <label>
                Пароль
                <input id="loginPasswordValue" name="password" autocomplete="current-password" type="password" required>
              </label>
              <div class="form-actions">
                <button id="loginAccountButton" type="submit">Войти</button>
                <button class="secondary" type="button" data-back-home>Назад</button>
              </div>
              <div class="error" id="loginAccountError"></div>
            </form>
          </div>
          <div class="view hidden" id="registerView">
            <form id="registerForm">
              <label>
                Логин или email
                <input id="registerLoginValue" name="login" autocomplete="username" placeholder="client@example.com" required>
              </label>
              <label>
                Пароль
                <input id="registerPasswordValue" name="password" autocomplete="new-password" type="password" required>
              </label>
              <label>
                Ссылка подписки, если уже есть
                <input id="registerKeyValue" name="key" autocomplete="off" inputmode="url" placeholder="<SUBSCRIPTION_URL>">
              </label>
              <div class="form-actions">
                <button id="registerButton" type="submit">Создать аккаунт</button>
                <button class="secondary" type="button" data-back-home>Назад</button>
              </div>
              <div class="error" id="registerError"></div>
            </form>
          </div>
          <div class="view hidden" id="existingUserView">
            <form id="loginForm">
              <label>
                Ссылка подписки
                <input id="loginValue" name="value" autocomplete="off" inputmode="url" placeholder="<SUBSCRIPTION_URL>" required>
              </label>
              <div class="form-actions">
                <button id="loginButton" type="submit">Открыть кабинет</button>
                <button class="secondary" type="button" data-back-home>Назад</button>
              </div>
              <div class="error" id="errorBox"></div>
            </form>
          </div>
          <div class="tiles">
            <div class="tile"><strong>Продление</strong><span>Текущий тариф и срок</span></div>
            <div class="tile"><strong>Оплата</strong><span>Внешние способы оплаты</span></div>
            <div class="tile"><strong>Подключение</strong><span>Основная подписка и подписка обхода БС</span></div>
          </div>
        </div>
      </section>
      <section class="steps">
        <article class="step"><span>1</span><h3>Выберите тариф</h3><p>Новый пользователь покупает доступ без Telegram и без предварительного ключа.</p></article>
        <article class="step"><span>2</span><h3>Оплатите на сайте</h3><p>Платежная ссылка создается через подключенный внешний способ оплаты.</p></article>
        <article class="step"><span>3</span><h3>Скопируйте профиль</h3><p>После оплаты откроется кабинет с основной ссылкой и дополнительным профилем, если он есть в тарифе.</p></article>
      </section>
    </main>
    <footer>AFZVPN кабинет работает на том же домене, что и подписки, и не требует новой регистрации.</footer>
  </div>
  <script>
    const modeButtons = document.querySelectorAll("[data-mode]");
    const newUserView = document.getElementById("newUserView");
    const loginView = document.getElementById("loginView");
    const registerView = document.getElementById("registerView");
    const existingUserView = document.getElementById("existingUserView");
    const plansList = document.getElementById("plansList");
    const newUserError = document.getElementById("newUserError");
    const accountBanner = document.getElementById("accountBanner");
    const form = document.getElementById("loginForm");
    const input = document.getElementById("loginValue");
    const button = document.getElementById("loginButton");
    const errorBox = document.getElementById("errorBox");
    const loginAccountForm = document.getElementById("loginAccountForm");
    const loginAccountButton = document.getElementById("loginAccountButton");
    const loginAccountError = document.getElementById("loginAccountError");
    const registerForm = document.getElementById("registerForm");
    const registerButton = document.getElementById("registerButton");
    const registerError = document.getElementById("registerError");
    let publicState = { gateways: [], purchase: { plans: [] } };

    const esc = (value) => String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");

    function showError(target, message) {
      target.textContent = message;
      target.classList.add("show");
    }

    function hideError(target) {
      target.classList.remove("show");
    }

    function setMode(mode) {
      modeButtons.forEach((item) => item.classList.toggle("active", item.dataset.mode === mode));
      newUserView.classList.toggle("hidden", mode !== "new");
      loginView.classList.toggle("hidden", mode !== "login");
      registerView.classList.toggle("hidden", mode !== "register");
      existingUserView.classList.toggle("hidden", mode !== "existing");
    }

    async function loadAccount() {
      try {
        const response = await fetch("/cabinet/api/me", { cache: "no-store" });
        if (!response.ok) return;
        const data = await response.json();
        if (!data.authenticated) return;
        accountBanner.innerHTML = `Вы вошли как ${esc(data.login)}. <a href="${esc(data.cabinet_url)}">Открыть мой кабинет</a> <button class="link-button" type="button" id="publicLogoutButton">Выйти</button>`;
        accountBanner.classList.add("show");
        const logoutButton = document.getElementById("publicLogoutButton");
        logoutButton?.addEventListener("click", async () => {
          await fetch("/cabinet/api/logout", { method: "POST" });
          window.location.reload();
        });
      } catch {}
    }

    function durationOptions(plan) {
      return (plan.durations || []).map((duration) => {
        const firstPrice = Object.values(duration.prices || {})[0];
        const suffix = firstPrice ? ` · ${firstPrice.price} ${firstPrice.symbol}` : "";
        const discount = duration.discount_percent ? ` · -${duration.discount_percent}%` : "";
        return `<option value="${duration.days}">${esc(duration.label + suffix + discount)}</option>`;
      }).join("");
    }

    function gatewayOptions(plan) {
      const duration = (plan.durations || [])[0];
      const prices = duration ? duration.prices || {} : {};
      return publicState.gateways
        .filter((gateway) => prices[gateway.id])
        .map((gateway) => {
          const price = prices[gateway.id];
          const label = price ? `${gateway.name} · ${price.price} ${price.symbol}` : gateway.name;
          return `<option value="${esc(gateway.id)}">${esc(label)}</option>`;
        })
        .join("");
    }

    function planCard(plan) {
      const gateways = gatewayOptions(plan);
      if (!gateways || !plan.durations.length) return "";
      const tags = [
        plan.devices_label,
        plan.includes_additional_profile ? "Подписка обхода БС" : null,
      ].filter(Boolean).map((tag) => `<span class="badge">${esc(tag)}</span>`).join("");
      return `
        <article class="plan-card ${plan.is_popular ? "popular" : ""}">
          <div class="plan-head">
            <h3>${esc(plan.title)}</h3>
            ${plan.is_popular ? `<span class="badge">Популярный</span>` : ""}
          </div>
          <div class="plan-meta">${tags}</div>
          <form class="new-purchase-form" data-plan-code="${esc(plan.code)}">
            <label>Срок<select name="duration" required>${durationOptions(plan)}</select></label>
            <label>Оплата<select name="gateway" required>${gateways}</select></label>
            <button type="submit">Купить</button>
          </form>
        </article>
      `;
    }

    async function loadPublicPlans() {
      try {
        const response = await fetch("/cabinet/api/public", { cache: "no-store" });
        if (!response.ok) throw new Error(await response.text() || "Не удалось загрузить тарифы.");
        publicState = await response.json();
        const html = publicState.purchase.plans.map(planCard).filter(Boolean).join("");
        plansList.innerHTML = html || `<div class="error show">Нет доступных тарифов для оплаты на сайте.</div>`;
        bindPurchaseForms();
      } catch (error) {
        plansList.innerHTML = `<div class="error show">${esc(error.message || "Не удалось загрузить тарифы.")}</div>`;
      }
    }

    function bindPurchaseForms() {
      document.querySelectorAll(".new-purchase-form").forEach((form) => {
        form.addEventListener("submit", async (event) => {
          event.preventDefault();
          hideError(newUserError);
          const submit = form.querySelector("button[type=submit]");
          const formData = new FormData(form);
          submit.disabled = true;
          try {
            const response = await fetch("/cabinet/api/start", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                plan_code: form.dataset.planCode,
                duration: formData.get("duration"),
                gateway: formData.get("gateway"),
              }),
            });
            if (!response.ok) throw new Error(await response.text() || "Не удалось создать оплату.");
            const data = await response.json();
            window.location.href = data.pay_url;
          } catch (error) {
            showError(newUserError, error.message || "Ошибка оплаты.");
          } finally {
            submit.disabled = false;
          }
        });
      });
    }

    modeButtons.forEach((item) => {
      item.addEventListener("click", () => setMode(item.dataset.mode));
    });

    document.querySelectorAll("[data-back-home]").forEach((item) => {
      item.addEventListener("click", () => setMode("new"));
    });

    loginAccountForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      hideError(loginAccountError);
      loginAccountButton.disabled = true;
      const formData = new FormData(loginAccountForm);
      try {
        const response = await fetch("/cabinet/api/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            login: formData.get("login"),
            password: formData.get("password"),
          }),
        });
        if (!response.ok) throw new Error(await response.text() || "Не удалось войти.");
        const data = await response.json();
        window.location.href = data.cabinet_url;
      } catch (error) {
        showError(loginAccountError, error.message || "Не удалось войти.");
      } finally {
        loginAccountButton.disabled = false;
      }
    });

    registerForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      hideError(registerError);
      registerButton.disabled = true;
      const formData = new FormData(registerForm);
      try {
        const response = await fetch("/cabinet/api/register", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            login: formData.get("login"),
            password: formData.get("password"),
            key: formData.get("key"),
          }),
        });
        if (!response.ok) throw new Error(await response.text() || "Не удалось создать аккаунт.");
        const data = await response.json();
        window.location.href = data.cabinet_url;
      } catch (error) {
        showError(registerError, error.message || "Не удалось создать аккаунт.");
      } finally {
        registerButton.disabled = false;
      }
    });

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      hideError(errorBox);
      button.disabled = true;
      try {
        const response = await fetch("/cabinet/resolve", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ value: input.value }),
        });
        if (!response.ok) {
          throw new Error(await response.text() || "Кабинет не найден.");
        }
        const data = await response.json();
        window.location.href = data.cabinet_url;
      } catch (error) {
        showError(errorBox, error.message || "Не удалось открыть кабинет.");
      } finally {
        button.disabled = false;
      }
    });

    loadPublicPlans();
    loadAccount();
  </script>
</body>
</html>
"""

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
      margin-bottom: 16px;
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
    .hero-strip {
      min-height: 210px;
      margin-bottom: 18px;
      padding: 24px;
      display: grid;
      align-content: end;
      border-radius: 8px;
      color: #ffffff;
      background:
        linear-gradient(180deg, rgba(9, 25, 31, .04), rgba(9, 25, 31, .78)),
        url("/assets/start_banner.jpg") center / cover no-repeat,
        #163138;
      box-shadow: var(--shadow);
    }
    .hero-strip h2 {
      margin: 0;
      max-width: 720px;
      color: #ffffff;
      font-size: clamp(28px, 4vw, 44px);
      line-height: 1.02;
    }
    .hero-strip p {
      max-width: 620px;
      margin-top: 10px;
      color: rgba(255, 255, 255, .86);
      font-size: 16px;
    }
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
    select, input {
      width: 100%;
      min-height: 42px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #ffffff;
      color: var(--text);
      padding: 0 10px;
    }
    input:focus, select:focus {
      outline: 3px solid rgba(8, 127, 140, .16);
      border-color: var(--accent);
    }
    .account-actions {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .account-form {
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid var(--line);
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
      .account-actions { grid-template-columns: 1fr; }
      .topbar { align-items: flex-start; }
      .pill { white-space: normal; justify-content: center; text-align: center; }
    }
    @media (max-width: 520px) {
      .shell { width: min(100% - 20px, 1040px); padding-top: 14px; }
      .status-grid { grid-template-columns: 1fr; }
      .topbar { display: grid; }
      .hero-strip { min-height: 260px; padding: 18px; }
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
    <section class="hero-strip">
      <div>
        <h2>Оплата, продление и ссылки профилей в одном месте</h2>
        <p>Кабинет работает даже тогда, когда подписка уже закончилась: выберите тариф, оплатите и верните доступ без лишних шагов.</p>
      </div>
    </section>
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
        plan.includes_additional_profile ? "Подписка обхода БС" : null,
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
        plan.includes_additional_profile ? "Подписка обхода БС" : null,
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
        state.links.primary_profile_url ? `<button class="secondary" type="button" data-copy="${esc(state.links.primary_profile_url)}">Скопировать основную подписку</button>` : "",
        state.links.filtered_additional_profile_url ? `<button class="secondary" type="button" data-copy="${esc(state.links.filtered_additional_profile_url)}">Скопировать обход БС — рекомендуется</button>` : "",
        state.links.additional_profile_url ? `<button class="secondary" type="button" data-copy="${esc(state.links.additional_profile_url)}">Скопировать обход БС — запасной вариант</button>` : "",
      ].join("");
      const accountButton = state.account.authenticated
        ? `<button class="secondary" type="button" data-logout>Выйти</button>`
        : `<a class="button secondary" href="/cabinet">Войти или зарегистрироваться</a>`;

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
            <a class="button secondary" href="/cabinet">Назад на сайт</a>
            ${accountButton}
            <a class="button secondary" href="${esc(state.cabinet_url)}">Обновить кабинет</a>
          </div>
        </section>
      `;
    }

    function renderAccount() {
      if (state.account.authenticated) {
        return `
          <section class="section">
            <h2>Аккаунт</h2>
            <div class="notice">
              Вы вошли как <strong>${esc(state.account.login)}</strong>.
              <div class="account-actions" style="margin-top:12px">
                <a class="button secondary" href="/cabinet">Назад на сайт</a>
                <button class="secondary" type="button" data-logout>Выйти</button>
              </div>
              <form class="account-form" id="bindKeyForm">
                <label>Привязать другую ссылку подписки<input name="value" autocomplete="off" inputmode="url" placeholder="<SUBSCRIPTION_URL>"></label>
                <button type="submit">Привязать подписку</button>
              </form>
            </div>
          </section>
        `;
      }

      return `
        <section class="section">
          <h2>Сохранить кабинет</h2>
          <div class="notice">
            Создайте логин и пароль, чтобы потом входить без ссылки подписки.
            <form class="account-form" id="registerCurrentForm">
              <label>Логин или email<input name="login" autocomplete="username" placeholder="client@example.com" required></label>
              <label>Пароль<input name="password" autocomplete="new-password" type="password" required></label>
              <button type="submit">Создать аккаунт для этого кабинета</button>
            </form>
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
          <h2>Подключить подписку обхода БС</h2>
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
        renderAccount(),
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

      document.querySelectorAll("[data-logout]").forEach((button) => {
        button.addEventListener("click", async () => {
          button.disabled = true;
          try {
            await fetch("/cabinet/api/logout", { method: "POST" });
            window.location.href = "/cabinet";
          } catch {
            window.location.href = "/cabinet";
          }
        });
      });

      const bindKeyForm = document.getElementById("bindKeyForm");
      if (bindKeyForm) {
        bindKeyForm.addEventListener("submit", async (event) => {
          event.preventDefault();
          const button = bindKeyForm.querySelector("button[type=submit]");
          const formData = new FormData(bindKeyForm);
          button.disabled = true;
          try {
            const response = await fetch("/cabinet/api/bind", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ value: formData.get("value") }),
            });
            if (!response.ok) throw new Error(await response.text() || "Не удалось привязать подписку.");
            const data = await response.json();
            window.location.href = data.cabinet_url;
          } catch (error) {
            showToast(error.message || "Не удалось привязать подписку.");
          } finally {
            button.disabled = false;
          }
        });
      }

      const registerCurrentForm = document.getElementById("registerCurrentForm");
      if (registerCurrentForm) {
        registerCurrentForm.addEventListener("submit", async (event) => {
          event.preventDefault();
          const button = registerCurrentForm.querySelector("button[type=submit]");
          const formData = new FormData(registerCurrentForm);
          button.disabled = true;
          try {
            const response = await fetch("/cabinet/api/register", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                login: formData.get("login"),
                password: formData.get("password"),
                key: state.cabinet_url,
              }),
            });
            if (!response.ok) throw new Error(await response.text() || "Не удалось создать аккаунт.");
            const data = await response.json();
            window.location.href = data.cabinet_url;
          } catch (error) {
            showToast(error.message || "Не удалось создать аккаунт.");
          } finally {
            button.disabled = false;
          }
        });
      }

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


def _extract_vpn_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    match = VPN_ID_PATTERN.search(value.strip())
    if not match:
        return None

    return match.group(0).lower()


def _generate_web_tg_id() -> int:
    return -((uuid.uuid4().int % WEB_USER_TG_ID_RANGE) + WEB_USER_TG_ID_MIN)


def _normalize_login(value: object) -> str:
    login = str(value or "").strip().lower()
    if not LOGIN_PATTERN.fullmatch(login):
        raise web.HTTPBadRequest(
            text="Логин должен быть от 3 до 128 символов: латиница, цифры, @ . _ + -"
        )
    return login


def _validate_password(value: object) -> str:
    password = str(value or "")
    if len(password) < 8:
        raise web.HTTPBadRequest(text="Пароль должен быть не короче 8 символов.")
    if len(password) > 256:
        raise web.HTTPBadRequest(text="Пароль слишком длинный.")
    return password


def _hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_HASH_ITERATIONS,
    )
    return (
        f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}$"
        f"{salt.hex()}${digest.hex()}"
    )


def _verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False

    try:
        algorithm, iterations_raw, salt_hex, digest_hex = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_raw)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (TypeError, ValueError):
        return False

    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual, expected)


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

    def _session_signature(self, tg_id: int, expires_at: int) -> str:
        secret = self.config.bot.TOKEN.encode("utf-8")
        payload = f"{tg_id}:{expires_at}".encode("utf-8")
        return hmac.new(secret, payload, hashlib.sha256).hexdigest()

    def _make_session_token(self, user: User) -> str:
        expires_at = int(time.time()) + ACCOUNT_SESSION_TTL_SECONDS
        signature = self._session_signature(user.tg_id, expires_at)
        return f"{user.tg_id}:{expires_at}:{signature}"

    def _is_secure_request(self, request: web.Request) -> bool:
        forwarded_proto = request.headers.get("X-Forwarded-Proto", "").lower()
        return request.secure or forwarded_proto == "https"

    def _set_account_cookie(
        self,
        response: web.StreamResponse,
        request: web.Request,
        user: User,
    ) -> None:
        response.set_cookie(
            ACCOUNT_COOKIE_NAME,
            self._make_session_token(user),
            max_age=ACCOUNT_SESSION_TTL_SECONDS,
            httponly=True,
            secure=self._is_secure_request(request),
            samesite="Lax",
            path="/",
        )

    def _clear_account_cookie(self, response: web.StreamResponse) -> None:
        response.del_cookie(ACCOUNT_COOKIE_NAME, path="/")

    async def _get_account_user(self, request: web.Request) -> User | None:
        token = request.cookies.get(ACCOUNT_COOKIE_NAME)
        if not token:
            return None

        try:
            tg_id_raw, expires_raw, signature = token.split(":", 2)
            tg_id = int(tg_id_raw)
            expires_at = int(expires_raw)
        except (TypeError, ValueError):
            return None

        if expires_at < int(time.time()):
            return None

        expected_signature = self._session_signature(tg_id, expires_at)
        if not hmac.compare_digest(signature, expected_signature):
            return None

        async with self.services.subscription.session_factory() as session:
            user = await User.get(session=session, tg_id=tg_id)

        if not user or not user.web_login:
            return None
        return user

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

    async def public_page(self, _: web.Request) -> web.Response:
        return web.Response(
            text=PUBLIC_TEMPLATE,
            content_type="text/html",
            charset="utf-8",
            headers={
                **NO_STORE_HEADERS,
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
            },
        )

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
        account_user = await self._get_account_user(request)
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
        get_filtered_additional_profile_url = getattr(
            self.services.subscription,
            "get_filtered_additional_profile_url",
            None,
        )
        filtered_additional_profile_url = (
            get_filtered_additional_profile_url(user)
            if status.has_additional_profile and get_filtered_additional_profile_url
            else None
        )

        return web.json_response(
            {
                "cabinet_url": self._cabinet_url(user),
                "user": {"name": user.first_name},
                "account": {
                    "authenticated": bool(
                        account_user and account_user.tg_id == user.tg_id
                    ),
                    "login": (
                        account_user.web_login
                        if account_user and account_user.tg_id == user.tg_id
                        else ""
                    ),
                    "current_account_url": (
                        self._cabinet_url(account_user) if account_user else ""
                    ),
                },
                "status": self._status_payload(user, status),
                "links": {
                    "primary_profile_url": primary_profile_url,
                    "additional_profile_url": additional_profile_url,
                    "filtered_additional_profile_url": filtered_additional_profile_url,
                },
                "gateways": [self._gateway_payload(gateway) for gateway in gateways],
                "purchase": {"plans": purchase_plans},
                "renew": renew,
                "upgrade": upgrade,
                "change": change,
            },
            headers=NO_STORE_HEADERS,
        )

    async def public_state(self, _: web.Request) -> web.Response:
        gateways = self._web_gateways()
        purchase_plans = [
            self._plan_payload(plan, gateways)
            for plan in self.services.plan.get_all_plans(
                prefer_additional_profile=True,
            )
        ]
        purchase_plans = [plan for plan in purchase_plans if plan["durations"]]

        return web.json_response(
            {
                "gateways": [self._gateway_payload(gateway) for gateway in gateways],
                "purchase": {"plans": purchase_plans},
            },
            headers=NO_STORE_HEADERS,
        )

    async def me(self, request: web.Request) -> web.Response:
        account_user = await self._get_account_user(request)
        return web.json_response(
            {
                "authenticated": bool(account_user),
                "login": account_user.web_login if account_user else "",
                "cabinet_url": self._cabinet_url(account_user) if account_user else "",
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

    async def _create_web_user(
        self,
        *,
        web_login: str | None = None,
        web_password_hash: str | None = None,
    ) -> User:
        async with self.services.subscription.session_factory() as session:
            return await self._create_web_user_in_session(
                session=session,
                web_login=web_login,
                web_password_hash=web_password_hash,
            )

    async def _create_web_user_in_session(
        self,
        *,
        session,
        web_login: str | None = None,
        web_password_hash: str | None = None,
    ) -> User:
        for _ in range(10):
            user = await User.create(
                session=session,
                tg_id=_generate_web_tg_id(),
                vpn_id=str(uuid.uuid4()),
                first_name=(web_login or WEB_USER_FIRST_NAME)[:32],
                username="web",
                web_login=web_login,
                web_password_hash=web_password_hash,
                language_code=WEB_USER_LANGUAGE,
            )
            if user:
                return user

        raise web.HTTPInternalServerError(text="Не удалось создать кабинет.")

    async def login(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        login = _normalize_login(payload.get("login"))
        password = str(payload.get("password") or "")

        async with self.services.subscription.session_factory() as session:
            user = await User.get_by_web_login(session=session, web_login=login)

        if not user or not _verify_password(password, user.web_password_hash):
            raise web.HTTPUnauthorized(text="Неверный логин или пароль.")

        response = web.json_response(
            {"cabinet_url": self._cabinet_url(user)},
            headers=NO_STORE_HEADERS,
        )
        self._set_account_cookie(response, request, user)
        return response

    async def register(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        login = _normalize_login(payload.get("login"))
        password = _validate_password(payload.get("password"))
        key_value = str(payload.get("key") or "").strip()
        password_hash = _hash_password(password)

        async with self.services.subscription.session_factory() as session:
            existing = await User.get_by_web_login(session=session, web_login=login)
            if existing:
                raise web.HTTPConflict(text="Этот логин уже занят.")

            target_user = None
            vpn_id = _extract_vpn_id(key_value)
            if vpn_id:
                target_user = await User.get_by_vpn_id(session=session, vpn_id=vpn_id)
                if not target_user:
                    raise web.HTTPNotFound(text="Подписка по этой ссылке не найдена.")
                if target_user.web_login:
                    raise web.HTTPConflict(text="Эта подписка уже привязана к аккаунту.")

            if target_user:
                await User.update(
                    session=session,
                    tg_id=target_user.tg_id,
                    web_login=login,
                    web_password_hash=password_hash,
                    first_name=target_user.first_name or login[:32],
                )
                user = await User.get(session=session, tg_id=target_user.tg_id)
            else:
                user = await self._create_web_user_in_session(
                    session=session,
                    web_login=login,
                    web_password_hash=password_hash,
                )

        if not user:
            raise web.HTTPInternalServerError(text="Не удалось создать аккаунт.")

        response = web.json_response(
            {"cabinet_url": self._cabinet_url(user)},
            headers=NO_STORE_HEADERS,
        )
        self._set_account_cookie(response, request, user)
        return response

    async def logout(self, _: web.Request) -> web.Response:
        response = web.json_response(
            {"ok": True, "cabinet_url": "/cabinet"},
            headers=NO_STORE_HEADERS,
        )
        self._clear_account_cookie(response)
        return response

    @staticmethod
    def _has_subscription_or_payments(user: User) -> bool:
        return bool(
            user.server_id
            or user.current_plan_code
            or getattr(user, "transactions", None)
        )

    async def bind_key(self, request: web.Request) -> web.Response:
        account_user = await self._get_account_user(request)
        if not account_user:
            raise web.HTTPUnauthorized(text="Сначала войдите в аккаунт.")

        payload = await self._read_json(request)
        vpn_id = _extract_vpn_id(payload.get("value"))
        if not vpn_id:
            raise web.HTTPBadRequest(text="Вставьте полную ссылку подписки.")

        async with self.services.subscription.session_factory() as session:
            current = await User.get(session=session, tg_id=account_user.tg_id)
            target = await User.get_by_vpn_id(session=session, vpn_id=vpn_id)
            if not current:
                raise web.HTTPUnauthorized(text="Сначала войдите в аккаунт.")
            if not target:
                raise web.HTTPNotFound(text="Подписка по этой ссылке не найдена.")
            if target.tg_id == current.tg_id:
                user = target
            elif target.web_login:
                raise web.HTTPConflict(text="Эта подписка уже привязана к аккаунту.")
            elif self._has_subscription_or_payments(current):
                raise web.HTTPConflict(
                    text="К этому аккаунту уже привязана другая подписка."
                )
            else:
                login = current.web_login
                password_hash = current.web_password_hash
                if not login or not password_hash:
                    raise web.HTTPUnauthorized(text="Сначала войдите в аккаунт.")

                await User.update(
                    session=session,
                    tg_id=current.tg_id,
                    web_login=None,
                    web_password_hash=None,
                )
                await User.update(
                    session=session,
                    tg_id=target.tg_id,
                    web_login=login,
                    web_password_hash=password_hash,
                )
                user = await User.get(session=session, tg_id=target.tg_id)

        if not user:
            raise web.HTTPInternalServerError(text="Не удалось привязать подписку.")

        response = web.json_response(
            {"cabinet_url": self._cabinet_url(user)},
            headers=NO_STORE_HEADERS,
        )
        self._set_account_cookie(response, request, user)
        return response

    async def start_purchase(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        gateway_id = str(payload.get("gateway") or "")
        gateway = self._get_web_gateway(gateway_id)
        user = await self._get_account_user(request)
        if user:
            status = await self.services.subscription.get_subscription_status(user)
            if status.is_active:
                raise web.HTTPConflict(
                    text="Для продления откройте свой кабинет и выберите продление."
                )
        else:
            user = await self._create_web_user()
        data = await self._build_payment_data(
            user=user,
            status=type("InactiveStatus", (), {"is_active": False})(),
            payload={**payload, "mode": "purchase"},
            gateway=gateway,
        )

        cabinet_url = self._cabinet_url(user)
        pay_url = await gateway.create_payment(data, return_url=cabinet_url)
        logger.info(
            "Web cabinet new purchase link created for web user %s gateway=%s.",
            user.tg_id,
            gateway_id,
        )
        return web.json_response(
            {
                "pay_url": pay_url,
                "cabinet_url": cabinet_url,
            },
            headers=NO_STORE_HEADERS,
        )

    async def resolve(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        vpn_id = _extract_vpn_id(payload.get("value"))
        if not vpn_id:
            raise web.HTTPBadRequest(text="Вставьте полную ссылку подписки или кабинета.")

        user, _ = await self.services.subscription.get_subscription_status_by_vpn_id(
            vpn_id
        )
        if not user:
            raise web.HTTPNotFound(text="Кабинет по этой ссылке не найден.")

        return web.json_response(
            {"cabinet_url": self._cabinet_url(user)},
            headers=NO_STORE_HEADERS,
        )

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
    assets_dir = BASE_DIR / "assets"
    if assets_dir.exists():
        app.router.add_static("/assets/", assets_dir, name="assets")
    app.router.add_get("/cabinet", cabinet.public_page)
    app.router.add_post("/cabinet/resolve", cabinet.resolve)
    app.router.add_get("/cabinet/api/public", cabinet.public_state)
    app.router.add_get("/cabinet/api/me", cabinet.me)
    app.router.add_post("/cabinet/api/login", cabinet.login)
    app.router.add_post("/cabinet/api/register", cabinet.register)
    app.router.add_post("/cabinet/api/logout", cabinet.logout)
    app.router.add_post("/cabinet/api/bind", cabinet.bind_key)
    app.router.add_post("/cabinet/api/start", cabinet.start_purchase)
    app.router.add_get("/cabinet/{vpn_id}", cabinet.page)
    app.router.add_get("/cabinet/{vpn_id}/api/state", cabinet.state)
    app.router.add_post("/cabinet/{vpn_id}/api/pay", cabinet.pay)
    app.router.add_post("/cabinet/{vpn_id}/api/change/apply", cabinet.apply_change)
