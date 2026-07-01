# Операции

## Ежедневные Проверки

```bash
docker ps
docker logs --tail=120 3xui-shop-bot
curl -I https://afzvpn.superbebra.uk/healthz
curl -fsS https://afzvpn.superbebra.uk/readyz
docker inspect --format='{{.State.Health.Status}}' 3xui-shop-bot
```

Проверить вручную:

- бот отвечает в Telegram;
- активная ссылка `/sub/{vpn_id}` открывается;
- подписка обхода БС открывается на тарифе с `includes_additional_profile`;
- платежные callbacks не сыпят ошибки;
- Redis container жив;
- `/readyz` возвращает `status: ok`;
- Docker health status для `3xui-shop-bot` равен `healthy`;
- в логах нет циклического restart loop.

## Деплой

```bash
docker compose up -d --build bot
docker logs --tail=120 3xui-shop-bot
```

Успешный старт обычно содержит:

- `Bot started`;
- `Start polling` или текущий webhook URL;
- `Web app started on 0.0.0.0:8080`;
- успешный Alembic upgrade.

## Polling И Webhook

Текущий режим задается `BOT_USE_WEBHOOK`.

Polling проще в эксплуатации, но держит постоянный long polling к Telegram API. Webhook лучше для production, если домен, TLS, reverse proxy и secret-path подготовлены. Перед переключением на webhook проверить:

- `BOT_DOMAIN` доступен по HTTPS;
- если используется `BOT_CABINET_DOMAIN`, он тоже доступен по HTTPS и проксирует на тот же web app;
- `/webhook` принимает `POST`;
- reverse proxy корректно прокидывает `X-Forwarded-*`;
- Telegram API доступен без нестабильного proxy.

## Бэкапы

Перед крупными изменениями сохранить:

- SQLite database из `app/data`;
- `.env`;
- `plans.json`;
- актуальные compose/deploy файлы;
- список docker images/containers.

Runtime state не коммитится в Git.

## Логи

Основной лог: `app/logs/app.log`.

Ротация управляется:

- `LOG_MAX_BYTES`;
- `LOG_BACKUP_COUNT`.

Логи могут содержать production-контекст, поэтому не отправлять их в публичные issues без редактирования.
