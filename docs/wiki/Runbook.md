# Runbook

## Бот Не Отвечает

1. Проверить контейнер:

```bash
docker ps | grep 3xui-shop-bot
docker logs --tail=120 3xui-shop-bot
```

2. Проверить доступность Telegram API и настроенный proxy.
3. Проверить Redis.
4. Перезапустить только bot service:

```bash
docker compose up -d --build bot
```

## Не Открывается Ссылка Подписки

1. Проверить `/healthz`.
2. Проверить логи бота по основной подписке или подписке обхода БС.
3. Проверить доступность 3X-UI panel.
4. Проверить fallback зеркал для источников подписки обхода БС.

## Проблема С Payment Callback

1. Убедиться, что gateway включен в `.env`.
2. Убедиться, что callback URL соответствует публичному домену.
3. Проверить transaction task logs.
