# Версионирование

Проект использует Semantic Versioning: `MAJOR.MINOR.PATCH`.

## Правила

- `MAJOR` - несовместимые изменения API, форматов ссылок, схемы данных или процесса деплоя.
- `MINOR` - новые возможности без поломки существующих ссылок и пользовательских сценариев.
- `PATCH` - исправления, тексты, документация, мелкие безопасные улучшения.

Текущая версия хранится в `VERSION`.

## Что считается публичным контрактом

- URL-пути подписок: `/sub/{vpn_id}`, `/wl/{vpn_id}`, `/wl-filtered/{vpn_id}`.
- Формат тарифов `plans.json`.
- Telegram callback-сценарии, видимые пользователю.
- Переменные окружения из `.env.example`.
- Миграции Alembic и совместимость существующей базы.

## Процесс изменения версии

1. Обновить `VERSION`.
2. Добавить запись в `CHANGELOG.md`.
3. Проверить тесты и синтаксис.
4. Создать git tag `vX.Y.Z`.
5. Опубликовать GitHub Release с выдержкой из changelog.

## Пример

```bash
printf "1.1.1\n" > VERSION
git add VERSION CHANGELOG.md
git commit -m "chore: release v1.1.1"
git tag -a v1.1.1 -m "v1.1.1"
git push origin main --tags
```
