# Security Policy

## Supported Version

Only the production `main` branch is actively supported.

## Reporting

Do not open public issues with secrets, tokens, database dumps, private URLs, or user data.

Report sensitive issues directly to the service maintainer/admin account used for production operations.

## Secret Handling

The following must never be committed:

- `.env` and staging env files
- Telegram bot tokens
- payment gateway keys
- 3X-UI credentials and tokens
- SQLite databases
- logs, backups, and migration bundles

Before pushing, run:

```bash
git status --short
git diff --cached --name-only
```

Confirm only source, docs, templates, and safe examples are staged.
