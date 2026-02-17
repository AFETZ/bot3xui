#!/usr/bin/env python3
"""
Generate one-time promocodes for legacy 3X-UI clients.

Legacy client in this script = client with non-numeric `email` in x-ui inbound settings.
Numeric emails are usually Telegram IDs already managed by the bot.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import secrets
import sqlite3
import string
from pathlib import Path

CHARSET = string.ascii_uppercase + string.digits
MS_PER_DAY = 24 * 60 * 60 * 1000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xui-db", default="/etc/x-ui/x-ui.db", help="Path to x-ui sqlite DB")
    parser.add_argument(
        "--bot-db",
        default="app/data/bot_database.sqlite3",
        help="Path to bot sqlite DB (with promocodes table)",
    )
    parser.add_argument(
        "--include-numeric-emails",
        action="store_true",
        help="Also include numeric emails (usually tg_id). Off by default.",
    )
    parser.add_argument(
        "--inbound-id",
        type=int,
        default=None,
        help="Process only specific inbound ID",
    )
    parser.add_argument(
        "--min-days",
        type=int,
        default=1,
        help="Skip clients with remaining days below this value",
    )
    parser.add_argument(
        "--unlimited-days",
        type=int,
        default=None,
        help="Assign this duration to clients with expiryTime=0 (unlimited). By default they are skipped.",
    )
    parser.add_argument(
        "--code-prefix",
        default="MIG",
        help="Promocode prefix (default: MIG)",
    )
    parser.add_argument(
        "--code-length",
        type=int,
        default=11,
        help="Total promocode length including prefix (default: 11)",
    )
    parser.add_argument(
        "--output-csv",
        default=f"legacy_promocodes_{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv",
        help="Output CSV file with mapping email -> promocode",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write to bot DB, only print and create CSV preview",
    )
    return parser.parse_args()


def normalize_days(expiry_time_ms: int, now_ms: int, min_days: int) -> int:
    remaining_ms = int(expiry_time_ms) - now_ms
    if remaining_ms <= 0:
        return 0
    remaining_days = math.ceil(remaining_ms / MS_PER_DAY)
    if remaining_days < min_days:
        return 0
    return remaining_days


def collect_legacy_clients(
    xui_db_path: Path,
    include_numeric_emails: bool,
    inbound_id: int | None,
    min_days: int,
    unlimited_days: int | None,
) -> tuple[list[dict], list[dict]]:
    now_ms = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    selected: dict[str, dict] = {}
    skipped: list[dict] = []

    with sqlite3.connect(xui_db_path) as conn:
        cur = conn.cursor()
        if inbound_id is None:
            rows = cur.execute("SELECT id, settings FROM inbounds").fetchall()
        else:
            rows = cur.execute("SELECT id, settings FROM inbounds WHERE id = ?", (inbound_id,)).fetchall()

    for ib_id, settings_json in rows:
        try:
            settings = json.loads(settings_json)
        except json.JSONDecodeError:
            skipped.append(
                {
                    "inbound_id": ib_id,
                    "email": "",
                    "client_id": "",
                    "reason": "broken_settings_json",
                }
            )
            continue

        for client in settings.get("clients", []):
            email = str(client.get("email", "")).strip()
            client_id = str(client.get("id", "")).strip()
            if not email:
                skipped.append(
                    {
                        "inbound_id": ib_id,
                        "email": "",
                        "client_id": client_id,
                        "reason": "empty_email",
                    }
                )
                continue

            if email.isdigit() and not include_numeric_emails:
                continue

            expiry_ms = int(client.get("expiryTime", 0) or 0)
            if expiry_ms <= 0:
                if unlimited_days is None:
                    skipped.append(
                        {
                            "inbound_id": ib_id,
                            "email": email,
                            "client_id": client_id,
                            "reason": "unlimited_skipped",
                        }
                    )
                    continue
                days = max(unlimited_days, min_days)
            else:
                days = normalize_days(expiry_ms, now_ms, min_days)
                if days <= 0:
                    skipped.append(
                        {
                            "inbound_id": ib_id,
                            "email": email,
                            "client_id": client_id,
                            "reason": "expired_or_too_small",
                        }
                    )
                    continue

            existing = selected.get(email)
            if not existing or days > existing["days"]:
                selected[email] = {
                    "inbound_id": ib_id,
                    "email": email,
                    "client_id": client_id,
                    "days": days,
                }

    result = sorted(selected.values(), key=lambda row: row["email"].lower())
    return result, skipped


def load_existing_codes(bot_db_path: Path) -> set[str]:
    with sqlite3.connect(bot_db_path) as conn:
        cur = conn.cursor()
        rows = cur.execute("SELECT code FROM promocodes").fetchall()
    return {row[0] for row in rows}


def generate_code(existing_codes: set[str], prefix: str, total_length: int) -> str:
    prefix = prefix.upper()
    suffix_len = max(total_length - len(prefix), 1)
    while True:
        suffix = "".join(secrets.choice(CHARSET) for _ in range(suffix_len))
        code = f"{prefix}{suffix}"
        if code not in existing_codes:
            existing_codes.add(code)
            return code


def insert_promocodes(bot_db_path: Path, prepared_rows: list[dict]) -> None:
    with sqlite3.connect(bot_db_path) as conn:
        cur = conn.cursor()
        for row in prepared_rows:
            cur.execute(
                """
                INSERT INTO promocodes (code, duration, is_activated, activated_by, created_at)
                VALUES (?, ?, 0, NULL, datetime('now'))
                """,
                (row["promocode"], row["days"]),
            )
        conn.commit()


def write_csv(output_csv: Path, rows: list[dict], skipped_rows: list[dict]) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "email",
                "inbound_id",
                "client_id",
                "days",
                "promocode",
                "status",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "email": row["email"],
                    "inbound_id": row["inbound_id"],
                    "client_id": row["client_id"],
                    "days": row["days"],
                    "promocode": row["promocode"],
                    "status": "prepared",
                }
            )
        for row in skipped_rows:
            writer.writerow(
                {
                    "email": row.get("email", ""),
                    "inbound_id": row.get("inbound_id", ""),
                    "client_id": row.get("client_id", ""),
                    "days": "",
                    "promocode": "",
                    "status": f"skipped:{row.get('reason', 'unknown')}",
                }
            )


def main() -> int:
    args = parse_args()
    xui_db = Path(args.xui_db)
    bot_db = Path(args.bot_db)
    output_csv = Path(args.output_csv)

    if not xui_db.exists():
        raise SystemExit(f"x-ui DB not found: {xui_db}")
    if not bot_db.exists():
        raise SystemExit(f"bot DB not found: {bot_db}")

    prepared, skipped = collect_legacy_clients(
        xui_db_path=xui_db,
        include_numeric_emails=args.include_numeric_emails,
        inbound_id=args.inbound_id,
        min_days=args.min_days,
        unlimited_days=args.unlimited_days,
    )

    existing_codes = load_existing_codes(bot_db)
    for row in prepared:
        row["promocode"] = generate_code(
            existing_codes=existing_codes,
            prefix=args.code_prefix,
            total_length=args.code_length,
        )

    write_csv(output_csv=output_csv, rows=prepared, skipped_rows=skipped)

    if args.dry_run:
        print("[DRY RUN] No DB writes were made.")
    else:
        insert_promocodes(bot_db_path=bot_db, prepared_rows=prepared)
        print(f"Inserted {len(prepared)} promocodes into bot DB.")

    print(f"Prepared clients: {len(prepared)}")
    print(f"Skipped clients: {len(skipped)}")
    print(f"CSV: {output_csv}")

    if prepared:
        sample = prepared[:5]
        print("\nSample:")
        for row in sample:
            print(f"- {row['email']}: {row['days']} days -> {row['promocode']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
