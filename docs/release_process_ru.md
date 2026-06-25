# Release Process

## Предрелизный чеклист

1. Проверить, что рабочее дерево чистое или содержит только релизные изменения.
2. Проверить `.env.example` на актуальность.
3. Проверить, что runtime state не попадет в Git:

```bash
git status --short
git diff --cached --name-only
```

4. Собрать переводы:

```bash
pybabel compile -d app/locales -D bot
```

5. Запустить тесты:

```bash
poetry run pytest
```

Если на хосте нет dev-зависимостей, использовать Docker:

```bash
docker run --rm -v "$PWD:/repo" -w /repo 3xui-shop-bot \
  sh -lc 'poetry install --no-interaction --no-root && poetry run python -m pytest'
```

## GitHub Wiki

Wiki-source хранится в `docs/wiki`, поэтому правки wiki проходят через Git вместе с кодом.
После релизного коммита синхронизируйте GitHub Wiki:

```bash
scripts/sync_github_wiki.sh
```

По умолчанию скрипт пушит в `git@github.com:AFETZ/bot3xui.wiki.git`.

## Деплой

```bash
docker compose up -d --build bot
docker logs --tail=120 3xui-shop-bot
```

Успешный старт содержит:

- `Bot started.`
- `Start polling` или текущий webhook URL
- `Web app started on 0.0.0.0:8080.`

## Rollback

1. Найти последний стабильный tag.
2. Вернуть дерево на tag или применить rollback patch.
3. Пересобрать контейнер:

```bash
docker compose up -d --build bot
```

4. Проверить логи и базовые пользовательские сценарии.
