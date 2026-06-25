# Платежи

## Поддерживаемые Методы

- Telegram Stars;
- YooKassa;
- YooMoney;
- Cryptomus;
- Heleket.

Каждый gateway включается отдельной переменной `SHOP_PAYMENT_*_ENABLED`.

## Callback Flow

1. Пользователь создает transaction в боте.
2. Gateway возвращает payment URL или invoice.
3. Пользователь оплачивает.
4. Gateway вызывает callback endpoint.
5. Бот проверяет transaction и idempotency.
6. Подписка создается или продлевается.

## Idempotency

Payment callback может прийти повторно. Обработка должна быть безопасной:

- не создавать двойное продление;
- не пересоздавать клиента без причины;
- сохранять понятный transaction status;
- логировать конфликтные состояния.

## Reconciliation

Фоновые задачи проверяют pending transactions, если gateway поддерживает запрос статуса. Это закрывает случаи, когда callback потерялся или пришел поздно.

## Операционный Чек

После изменения billing-кода:

- прогнать payment tests;
- проверить один безопасный тестовый платеж;
- проверить логи callback endpoint;
- проверить, что пользователь получил подписку;
- проверить, что повторный callback не меняет срок второй раз.
