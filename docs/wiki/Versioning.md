# Версионирование

Проект использует Semantic Versioning: `MAJOR.MINOR.PATCH`.

Текущая версия хранится в `VERSION`.

## Правила

| Тип | Когда повышать |
| --- | --- |
| `MAJOR` | несовместимые изменения URL, схемы данных, migrations или deploy-процесса |
| `MINOR` | новые возможности без поломки существующих ссылок и пользовательских сценариев |
| `PATCH` | исправления, тексты, документация, низкорисковые улучшения |

## Публичный Контракт

Считать публичным контрактом:

- `/sub/{vpn_id}`;
- `/wl-filtered/{vpn_id}`;
- `/wl/{vpn_id}`;
- `/connection`;
- формат `plans.json`;
- `.env.example`;
- Alembic migrations;
- user-facing Telegram navigation.

## Каждый Релиз Обновляет

- `VERSION`;
- `CHANGELOG.md`;
- Git tag `vX.Y.Z`;
- GitHub Release notes;
- wiki-source в `docs/wiki`, если менялись процессы или поведение.

## Пример

```bash
printf "1.1.1\n" > VERSION
git add VERSION CHANGELOG.md docs/wiki
git commit -m "chore: release v1.1.1"
git tag -a v1.1.1 -m "v1.1.1"
git push origin main --tags
```
