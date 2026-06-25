# Changelog

All notable changes to this project are documented here.

The format follows Keep a Changelog, and releases use Semantic Versioning.

## [Unreleased]

### Changed

- Polished the project README as a production-facing overview.
- Expanded versioned GitHub Wiki source with operations, configuration, connection modes, user flows, payments, and contributors documentation.

## [1.1.0] - 2026-06-25

### Added

- Filtered whitelist-bypass subscription endpoint: `/wl-filtered/{vpn_id}`.
- Recommended and backup whitelist-bypass subscription buttons.
- Server-side fallback mirrors for `igareck/vpn-configs-for-russia`.
- Repository governance baseline: CI, issue templates, PR template, security policy, release/versioning docs, and wiki source.
- Versioned GitHub Wiki source under `docs/wiki` with a sync script.
- `poetry.lock` for reproducible dependency resolution.

### Changed

- Android onboarding now uses the same Happ-only connection flow as iOS and Windows.
- Connection buttons now separate the main subscription from the whitelist-bypass subscription.
- RU services routing button uses user-facing production wording.
- Docker build context excludes runtime state, databases, logs, local caches, and backups.
- Docker builds now install from `poetry.lock`.

### Removed

- Client choice screen for Android.
- Raw configuration button from user-facing connection flows.

## [1.0.0] - 2026-06-18

### Added

- Production baseline for AFZVPN Telegram bot.
- Main subscription proxy `/sub/{vpn_id}`.
- Whitelist-bypass subscription proxy `/wl/{vpn_id}`.
- Multi-server profile aggregation and Happ onboarding.
- Subscription, payment, referral, admin, and web-cabinet flows.
