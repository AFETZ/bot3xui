# Конфигурация

## `.env`

Основной пример: `.env.example`.

Ключевые группы:

- Telegram: `BOT_TOKEN`, `BOT_ADMINS`, `BOT_DEV_ID`;
- публичный домен: `BOT_DOMAIN`, `BOT_HOST`;
- режим Telegram updates: `BOT_USE_WEBHOOK`;
- proxy: `BOT_PROXY_URL`, `BOT_PROXY_STRICT`, `BOT_PROXY_CHECK_TIMEOUT`;
- 3X-UI: `XUI_USERNAME`, `XUI_PASSWORD`, `XUI_SUBSCRIPTION_*`;
- payments: `SHOP_PAYMENT_*_ENABLED` и gateway secrets;
- logs: `LOG_LEVEL`, `LOG_MAX_BYTES`, `LOG_BACKUP_COUNT`.

## `plans.json`

Тарифы задаются в `plans.json`.

Важные поля:

- `code`;
- `title`;
- `devices`;
- `prices`;
- `is_public`;
- `is_popular`;
- `includes_additional_profile`;
- `upgrade_from`.

`includes_additional_profile: true` открывает подписку обхода БС.

## Runtime State

Не коммитить:

- `.env`;
- `.env.staging`;
- `app/data`;
- `app/logs`;
- `.local`;
- `.venv`;
- `backups`;
- compiled `.mo`.

## Docker

Production service:

```bash
docker compose up -d --build bot
```

Staging service использует `docker-compose.staging.yml` и отдельный `.env.staging`.
