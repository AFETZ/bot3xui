# Операции

## Ежедневные Проверки

- Container status: `docker ps`.
- Bot logs: `docker logs --tail=120 3xui-shop-bot`.
- Health endpoint: `curl -I https://afzvpn.superbebra.uk/healthz`.
- Smoke-test подписки с активным `vpn_id`.

## Runtime Files

Не коммитить:

- `.env`
- `.local/`
- `app/data/`
- `app/logs/`
- `backups/`

## Restart

```bash
docker compose up -d --build bot
docker logs --tail=120 3xui-shop-bot
```
