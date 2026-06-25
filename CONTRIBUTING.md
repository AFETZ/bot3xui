# Contributing

This repository is operated as a production service. Changes should be small, reviewable, and safe to deploy.

## Workflow

1. Create a branch from `main`.
2. Keep runtime state out of Git: `.env`, `.local/`, `app/data/`, `app/logs/`, `backups/`.
3. Update tests and docs when behavior changes.
4. Run the focused test set locally or through Docker.
5. Open a pull request with a short risk and rollback note.

## Local Checks

```bash
python3 -m compileall app tests
```

When dependencies are available:

```bash
poetry run pybabel compile -d app/locales -D bot
poetry run pytest
```

The production Docker image can also run focused tests:

```bash
docker run --rm -v "$PWD:/repo" -w /repo 3xui-shop-bot \
  sh -lc 'poetry install --no-interaction --no-root && poetry run python -m pytest tests/test_download_keyboard.py'
```

## Release Discipline

- User-facing behavior changes require a `CHANGELOG.md` entry.
- Version changes are recorded in `VERSION`.
- See `docs/versioning_ru.md` and `docs/release_process_ru.md`.
