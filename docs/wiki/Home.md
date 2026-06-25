# AFZVPN Bot Wiki

Добро пожаловать в рабочую wiki AFZVPN Bot. Эта документация хранится в `docs/wiki`, синхронизируется в GitHub Wiki и версионируется вместе с кодом.

## Быстрая Навигация

| Раздел | Для чего |
| --- | --- |
| [Архитектура](Architecture.md) | компоненты, публичные endpoints, границы ответственности |
| [Пользовательские сценарии](User-Flows.md) | покупка, подключение, апгрейд, подписка обхода БС |
| [Режимы подключения](Connection-Modes.md) | основная подписка, РФ-сервисы напрямую, обход БС |
| [Конфигурация](Configuration.md) | `.env`, `plans.json`, secrets, runtime state |
| [Платежи](Payments.md) | шлюзы, callbacks, idempotency, reconciliation |
| [Операции](Operations.md) | ежедневные проверки, деплой, бэкапы, polling/webhook |
| [Runbook](Runbook.md) | что делать при инцидентах |
| [Релизный чеклист](Release-Checklist.md) | порядок релиза |
| [Версионирование](Versioning.md) | SemVer, публичные контракты, changelog |
| [Contributors](Contributors.md) | почему GitHub показывает несколько авторов |

## Production Snapshot

- Основная ветка: `main`.
- Текущий release: `v1.1.0`.
- Runtime: Docker Compose, Redis, SQLite, aiohttp web app, aiogram bot.
- Пользовательский клиент: Happ для iOS, Android и Windows.
- Основная подписка: `/sub/{vpn_id}`.
- Подписка обхода БС:
  - рекомендуемый вариант: `/wl-filtered/{vpn_id}`;
  - запасной вариант: `/wl/{vpn_id}`.

## Главные Правила

- Не коммитить `.env`, базы, логи, backups, `.local`, `.venv`.
- Перед релизом запускать тесты и `git diff --cached --check`.
- Любое изменение пользовательского флоу отражать в README, wiki и `CHANGELOG.md`.
- Основная подписка и подписка обхода БС должны оставаться понятными пользователю как разные подключения.
