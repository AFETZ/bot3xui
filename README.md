# AFZVPN Bot

Production Telegram bot for selling and managing VPN subscriptions through 3X-UI.

[![Release](https://img.shields.io/github/v/tag/AFETZ/bot3xui?label=release)](https://github.com/AFETZ/bot3xui/tags)
[![CI](https://github.com/AFETZ/bot3xui/actions/workflows/ci.yml/badge.svg)](https://github.com/AFETZ/bot3xui/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/)
[![Telegram](https://img.shields.io/badge/Telegram-bot-229ED9)](https://telegram.org/)
[![License](https://img.shields.io/github/license/AFETZ/bot3xui)](LICENSE)

## Что Это

**AFZVPN Bot** - продовая версия Telegram-бота для продажи VPN-подписок. Он связывает пользователей Telegram, оплаты, клиентов 3X-UI, тарифы, промокоды, поддержку и админские инструменты в один рабочий сервис.

Проект вырос из идеи `3xui-shop`, но этот репозиторий поддерживается как кастомная сборка AFZVPN: с продовыми правками, Happ-онбордингом, подпиской обхода БС, админкой и операционными скриптами.

## Основные Возможности

- Telegram-бот для продажи и управления VPN-подписками
- интеграция с 3X-UI для создания, продления, проверки и управления клиентами
- тарифы с разными сроками, валютами и количеством устройств
- one-click подключение в Happ для iOS, Android и Windows
- **РФ-сервисы напрямую, остальное через VPN**: отдельный режим Happ для удобной работы российских сервисов
- прокси основного профиля `/sub/{vpn_id}` с проверкой активной подписки
- подписка обхода БС для тарифов, где она включена
- рекомендуемый источник обхода БС `/wl-filtered/{vpn_id}` и запасной источник `/wl/{vpn_id}`
- пробный период и реферальные бонусы
- многоразовые промокоды с лимитами активаций
- платежи: Telegram Stars, YooKassa, YooMoney, Cryptomus, Heleket
- админка для пользователей, статистики, серверов, промокодов, уведомлений, бэкапов, техрежима и рестарта
- polling или webhook режим
- Redis FSM storage, SQLite, Alembic, Docker

## Пользовательский Путь

1. Пользователь открывает Telegram-бота.
2. Выбирает тариф, срок и способ оплаты.
3. После оплаты бот создает или продлевает клиента в 3X-UI.
4. Пользователь открывает **Профиль -> Подключиться -> Выбор платформы**.
5. Бот дает кнопки:
   - **Подключить основную подписку**
   - **РФ-сервисы напрямую, остальное через VPN**
   - **Подписка обхода БС — рекомендуется**, если она включена в тариф
   - **Подписка обхода БС — запасной вариант**, если рекомендованный вариант не подошел

Основная подписка и подписка обхода БС - разные подключения. БС означает "белые списки"; этот термин уже используется в тарифах и поддержке.

## Режим Для РФ

Режим **РФ-сервисы напрямую, остальное через VPN** - отдельная настройка Happ, чтобы пользователю не приходилось постоянно включать и выключать VPN:

- российские домены и российские IP идут напрямую
- зарубежные сервисы продолжают идти через VPN
- настройка включается одной кнопкой: **Профиль -> Подключиться -> Выбор платформы -> РФ-сервисы напрямую, остальное через VPN**

Это удобно, если пользователю нужны российские банки, маркетплейсы, госуслуги и локальные приложения, но при этом зарубежные сервисы должны оставаться доступными через VPN.

Маршруты могут донастраиваться по обратной связи пользователей.

## Админка

В боте есть админский раздел для ежедневной эксплуатации:

- поиск пользователей и карточка пользователя
- контекст подписки и оплат
- статистика бота
- управление пулом серверов
- создание, редактирование и удаление промокодов
- массовые и личные уведомления
- резервные копии базы
- режим обслуживания
- рестарт бота из Telegram

## Web Routes

| Route | Назначение |
| --- | --- |
| `/healthz` | health check |
| `/webhook` | Telegram webhook |
| `/connection` | redirect для deep-link в Happ |
| `/sub/{vpn_id}` | прокси основного профиля |
| `/wl-filtered/{vpn_id}` | рекомендуемая подписка обхода БС |
| `/wl/{vpn_id}` | запасная подписка обхода БС |
| `/yookassa` | YooKassa webhook |
| `/yoomoney` | YooMoney webhook |
| `/cryptomus` | Cryptomus webhook |
| `/heleket` | Heleket webhook |

## Stack

- Python 3.12
- aiogram 3
- aiohttp
- SQLAlchemy + Alembic
- SQLite
- Redis
- APScheduler
- py3xui
- Docker Compose
- Traefik-compatible deployment

## Быстрый Старт

Нужно заранее подготовить:

- Docker и Docker Compose
- Telegram bot token
- доступы к 3X-UI
- публичный HTTPS-домен для webhook и connection links

```bash
git clone https://github.com/AFETZ/bot3xui.git
cd bot3xui
cp .env.example .env
```

Заполните `.env` и настройте `plans.json`, затем запустите:

```bash
docker compose up -d --build
```

Только продовый bot service:

```bash
docker compose up -d --build bot
```

## Важные Переменные Окружения

| Variable | Для чего |
| --- | --- |
| `BOT_TOKEN` | токен Telegram-бота |
| `BOT_DEV_ID` | Telegram ID разработчика |
| `BOT_ADMINS` | Telegram ID админов через запятую |
| `BOT_DOMAIN` | публичный домен, например `https://example.com` |
| `BOT_HOST` | host для Traefik labels или deploy-конфига |
| `BOT_USE_WEBHOOK` | `True` для webhook, `False` для polling |
| `BOT_PROXY_URL` | optional SOCKS5 proxy для Telegram API; если proxy недоступен, бот стартует без него |
| `BOT_PROXY_STRICT` | `True`, если недоступный `BOT_PROXY_URL` должен останавливать старт |
| `BOT_PROXY_CHECK_TIMEOUT` | таймаут проверки proxy в секундах |
| `XUI_USERNAME` | логин 3X-UI |
| `XUI_PASSWORD` | пароль 3X-UI |
| `XUI_SUBSCRIPTION_SCHEME` | схема subscription URL |
| `XUI_SUBSCRIPTION_PORT` | порт подписки |
| `XUI_SUBSCRIPTION_PATH` | path подписки |
| `SHOP_CURRENCY` | основная валюта магазина |
| `LOG_MAX_BYTES` | максимальный размер `app/logs/app.log`, по умолчанию 10485760 |
| `LOG_BACKUP_COUNT` | сколько архивов `app.log` хранить, по умолчанию 5 |
| `SHOP_PAYMENT_STARS_ENABLED` | включить Telegram Stars |
| `SHOP_PAYMENT_YOOKASSA_ENABLED` | включить YooKassa |
| `SHOP_PAYMENT_YOOMONEY_ENABLED` | включить YooMoney |
| `SHOP_PAYMENT_CRYPTOMUS_ENABLED` | включить Cryptomus |
| `SHOP_PAYMENT_HELEKET_ENABLED` | включить Heleket |

Не коммитьте `.env`, дампы базы, Redis data, сертификаты, логи и локальные runtime-файлы.

## Тарифы

Тарифы настраиваются в `plans.json`.

Поддерживаемые поля:

- `code`
- `title`
- `devices`
- `prices`
- `is_public`
- `is_popular`
- `includes_additional_profile`
- `upgrade_from`

Тарифы с `includes_additional_profile: true` открывают подписку обхода БС.

## Тесты

Полный прогон:

```bash
./.venv/bin/pytest
```

Через Poetry:

```bash
poetry run pytest
```

Последняя проверка перед baseline-коммитом:

```text
21 passed
```

## Production Notes

- `main` - продовая ветка.
- `v1.1.0` - текущий baseline release этой кастомной AFZVPN-сборки.
- Runtime state живет вне Git: `.env`, `.local/`, Redis data, logs, certs, database backups.
- Перед крупными деплоями делайте backup bundle и архив рабочего дерева.

## Credits

Проект вырос из open-source экосистемы `3xui-shop` и адаптирован под production-задачи AFZVPN.

Запасная подписка обхода БС `/wl/{vpn_id}` отдает Universal-подписку через
серверный fallback по зеркалам. Пользовательская ссылка остается одной и той же.

Рекомендуемая подписка обхода БС `/wl-filtered/{vpn_id}` отдает легкую
мобильную подписку из `igareck/vpn-configs-for-russia` через отдельный fallback
по зеркалам. Доступ открыт тем же тарифам с `includes_additional_profile`.

Внешние источники правил для подписки обхода БС:

- https://github.com/zieng2/wl
- https://github.com/igareck/vpn-configs-for-russia
