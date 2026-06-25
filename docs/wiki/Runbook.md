# Runbook

## Бот Не Отвечает

1. Проверить контейнер:

```bash
docker ps | grep 3xui-shop-bot
docker logs --tail=160 3xui-shop-bot
```

2. Проверить Redis:

```bash
docker ps | grep 3xui-shop-redis
```

3. Проверить Telegram connectivity и `BOT_PROXY_URL`.
4. Перезапустить только bot service:

```bash
docker compose up -d --build bot
```

## Не Открывается Основная Подписка

1. Проверить `/healthz`.
2. Проверить, активна ли подписка пользователя.
3. Проверить доступность 3X-UI.
4. Проверить логи `app.web.primary_profile`.
5. Если проблема только в одном пользователе, проверить `vpn_id`, server binding и наличие клиента в 3X-UI.

## Не Работает Подписка Обхода БС

1. Убедиться, что тариф содержит `includes_additional_profile: true`.
2. Проверить `/wl-filtered/{vpn_id}`.
3. Если рекомендуемый вариант недоступен, проверить `/wl/{vpn_id}`.
4. Смотреть логи `app.web.additional_profile`.
5. Проверить зеркала внешних источников.

## Payment Callback Issue

1. Проверить, включен ли gateway в `.env`.
2. Сверить callback URL в кабинете платежного шлюза.
3. Проверить transaction status в базе.
4. Проверить idempotency: один callback не должен создавать двойное продление.
5. Запустить reconciliation job или дождаться фоновой задачи, если gateway поддерживает проверку статуса.

## После Неудачного Деплоя

1. Не удалять runtime state.
2. Проверить последний стабильный commit или tag.
3. Вернуть код на стабильный commit.
4. Пересобрать bot service.
5. Проверить `/healthz`, Telegram response и одну активную подписку.
