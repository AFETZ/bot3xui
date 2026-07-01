# Релизный Чеклист

## Перед Коммитом

1. Проверить рабочее дерево:

```bash
git status --short --ignored
git diff --check
```

2. Убедиться, что не staged:

- `.env`;
- SQLite базы;
- логи;
- backups;
- `.local`;
- `.venv`;
- `.mo`;
- private keys и payment secrets.

3. Запустить тесты:

```bash
docker run --rm -v "$PWD:/repo" -w /repo 3xui-shop-bot \
  sh -lc 'poetry install --no-interaction --no-root && poetry run python -m pytest tests'
```

## Релиз

1. Обновить `VERSION`.
2. Обновить `CHANGELOG.md`.
3. Сделать commit.
4. Создать tag `vX.Y.Z`.
5. Запушить branch и tag.
6. Создать GitHub Release.
7. Убедиться, что release workflow прикрепил source archive.
8. Синхронизировать GitHub Wiki:

```bash
scripts/sync_github_wiki.sh https://github.com/AFETZ/bot3xui.wiki.git
```

## После Деплоя

1. Проверить логи.
2. Проверить `/healthz` и `/readyz`.
3. Проверить Telegram bot response.
4. Проверить активную `/sub/{vpn_id}`.
5. Проверить кнопки подключения Happ.
6. Проверить платежный callback в безопасном тестовом сценарии, если релиз затрагивал billing.
