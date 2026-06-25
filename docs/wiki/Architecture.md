# Архитектура

## Runtime

- `3xui-shop-bot` запускает Telegram-бота и aiohttp web app.
- `3xui-shop-redis` хранит FSM/background state.
- Traefik завершает HTTPS и проксирует публичный трафик на порт бота `8080`.
- Панели 3X-UI остаются источником правды для VPN-клиентов и inbound.

## Public Endpoints

- `/healthz` - health check.
- `/sub/{vpn_id}` - основная подписка.
- `/wl-filtered/{vpn_id}` - рекомендуемая подписка обхода БС.
- `/wl/{vpn_id}` - запасная подписка обхода БС.
- `/cabinet/{vpn_id}` - личный кабинет пользователя.
- payment gateway callbacks по настройкам платежных шлюзов.

## Data Ownership

- Bot database: пользователи, транзакции, промокоды, локальные снимки подписок.
- 3X-UI: реальные клиенты, трафик, сроки, состояние inbound.
- `plans.json`: каталог тарифов.
