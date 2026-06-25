# AFZVPN Bot Wiki

Эта папка хранит wiki-source в обычном Git. Так wiki версионируется вместе с кодом и может синхронизироваться в GitHub Wiki.

## Разделы

- [Архитектура](Architecture.md)
- [Операции](Operations.md)
- [Версионирование](Versioning.md)
- [Релизный чеклист](Release-Checklist.md)
- [Runbook](Runbook.md)

## Production Snapshot

- Telegram-бот для подписок AFZVPN.
- Основная подписка: `/sub/{vpn_id}`.
- Подписка обхода БС:
  - рекомендуется: `/wl-filtered/{vpn_id}`;
  - запасной вариант: `/wl/{vpn_id}`.
- Runtime: Docker Compose, Redis, внешний Traefik.
