#!/usr/bin/env python3
"""Send review-approved creator outreach emails through a configured SMTP inbox.

Safety defaults:
- Dry-run by default: no network connection and no email is sent.
- A row needs review_status=approved and a public primary_email.
- Sending requires both --send and --yes-send-approved.
- Rows already marked sent or opted out are skipped.

Configure SMTP values in outputs/.env. This script is intended for small,
human-reviewed batches, not unsolicited bulk mail.
"""

from __future__ import annotations

import argparse
import csv
import os
import smtplib
import sys
import time
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from pathlib import Path
from typing import Any


ADDED_QUEUE_FIELDS = ["last_outreach_at", "last_outreach_error"]
LOG_FIELDS = ["candidate_id", "email", "event", "timestamp", "details"]
BLOCKED_STATUSES = {"sent", "opted_out", "unsubscribed", "do_not_contact", "bounced"}
ALLOWED_STATUSES = {"", "not_started", "dry_run_ready", "failed"}


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_dotenv() -> dict[str, str]:
    path = Path(__file__).resolve().parent / ".env"
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def setting(name: str, dotenv: dict[str, str], default: str = "") -> str:
    return os.getenv(name, "").strip() or dotenv.get(name, "").strip() or default


def clean_header(value: str, label: str) -> str:
    if "\n" in value or "\r" in value:
        raise ValueError(f"{label} cannot contain a line break.")
    return value.strip()


def is_email(value: str) -> bool:
    _, address = parseaddr(value)
    return bool(address and "@" in address and "." in address.rsplit("@", 1)[-1])


class TemplateValues(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return ""


def render_text(template: str, row: dict[str, str], config: dict[str, str]) -> str:
    values = TemplateValues(
        creator_name=row.get("creator_name", "") or row.get("handle", "") or "there",
        handle=row.get("handle", ""),
        platform=row.get("platform", ""),
        profile_url=row.get("profile_url", ""),
        campaign_angle=row.get("campaign_angle", "") or "a paid creator collaboration",
        personalization_note=row.get("personalization_note", "") or "your content",
        sender_name=config["sender_name"],
        brand_name=config["brand_name"],
        postal_address=config["postal_address"],
        unsubscribe_email=config["unsubscribe_email"],
    )
    try:
        return template.format_map(values).strip()
    except ValueError as error:
        raise ValueError(f"Invalid template placeholder syntax: {error}") from error


def email_body(template: str, row: dict[str, str], config: dict[str, str]) -> str:
    """Use an AI draft only after it has survived the normal approval gate."""
    draft = (row.get("ai_email_body") or "").strip()
    if not draft:
        return render_text(template, row, config)
    footer = (
        f"Best,\n{config['sender_name']}\n{config['brand_name']}\n{config['postal_address']}\n\n"
        f'To stop receiving partnership emails from us, reply "unsubscribe" to {config["unsubscribe_email"]}.'
    )
    return f"{draft}\n\n{footer}"


def load_template(path: str) -> str:
    template = Path(path).read_text(encoding="utf-8")
    if not template.strip():
        raise ValueError("Email template is empty.")
    return template


def validate_send_config(config: dict[str, str]) -> None:
    required = {
        "OUTREACH_SMTP_HOST": config["smtp_host"],
        "OUTREACH_SMTP_USERNAME": config["smtp_username"],
        "OUTREACH_SMTP_PASSWORD": config["smtp_password"],
        "OUTREACH_FROM_EMAIL": config["from_email"],
        "OUTREACH_POSTAL_ADDRESS": config["postal_address"],
        "OUTREACH_UNSUBSCRIBE_EMAIL": config["unsubscribe_email"],
        "--brand-name": config["brand_name"],
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ValueError("Missing required sending settings: " + ", ".join(missing))
    if not is_email(config["from_email"]):
        raise ValueError("OUTREACH_FROM_EMAIL is not a valid email address.")
    if not is_email(config["unsubscribe_email"]):
        raise ValueError("OUTREACH_UNSUBSCRIBE_EMAIL is not a valid email address.")


def send_message(email: str, subject: str, body: str, config: dict[str, str]) -> None:
    message = EmailMessage()
    message["From"] = formataddr((config["from_name"], config["from_email"]))
    message["To"] = email
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(config["smtp_host"], int(config["smtp_port"]), timeout=45) as server:
        server.ehlo()
        if config["starttls"] == "yes":
            server.starttls()
            server.ehlo()
        server.login(config["smtp_username"], config["smtp_password"])
        server.send_message(message)


def write_csv(path: str, fields: list[str], rows: list[dict[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send small, review-approved creator outreach batches via SMTP.")
    parser.add_argument("--input", required=True, help="Approved outreach queue CSV.")
    parser.add_argument("--out", default="outreach_queue_after_send.csv", help="Updated queue CSV.")
    parser.add_argument("--log", default="outreach_send_log.csv", help="Send audit log CSV.")
    parser.add_argument("--template", default="outreach_email_template.txt", help="Plain-text email template.")
    parser.add_argument("--brand-name", default="", help="Brand shown in the message. Required when sending.")
    parser.add_argument("--sender-name", default="Partnerships Team", help="Name shown in the message and From header.")
    parser.add_argument("--subject", default="Paid collaboration opportunity with {brand_name}")
    parser.add_argument("--max-send", type=int, default=10, help="Maximum approved emails in this run.")
    parser.add_argument("--pause", type=float, default=45, help="Seconds between real emails.")
    parser.add_argument("--dry-run", action="store_true", help="Explicitly preview only; this is already the default.")
    parser.add_argument("--send", action="store_true", help="Actually send email. Default is a safe dry-run.")
    parser.add_argument("--yes-send-approved", action="store_true", help="Required acknowledgement before real sending.")
    parser.add_argument("--no-starttls", action="store_true", help="Only for SMTP providers that explicitly do not use STARTTLS.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.max_send < 1:
        raise SystemExit("--max-send must be at least 1.")
    if args.pause < 0:
        raise SystemExit("--pause cannot be negative.")
    if args.send and not args.yes_send_approved:
        raise SystemExit("Refusing to send. Add --yes-send-approved after checking every approved row.")
    if args.send and args.dry_run:
        raise SystemExit("Choose either --dry-run or --send, not both.")

    dotenv = read_dotenv()
    config = {
        "smtp_host": setting("OUTREACH_SMTP_HOST", dotenv),
        "smtp_port": setting("OUTREACH_SMTP_PORT", dotenv, "587"),
        "smtp_username": setting("OUTREACH_SMTP_USERNAME", dotenv),
        "smtp_password": setting("OUTREACH_SMTP_PASSWORD", dotenv),
        "from_email": setting("OUTREACH_FROM_EMAIL", dotenv),
        "from_name": args.sender_name.strip(),
        "postal_address": setting("OUTREACH_POSTAL_ADDRESS", dotenv),
        "unsubscribe_email": setting("OUTREACH_UNSUBSCRIBE_EMAIL", dotenv),
        "brand_name": args.brand_name.strip(),
        "sender_name": args.sender_name.strip(),
        "starttls": "no" if args.no_starttls else "yes",
    }
    try:
        config["smtp_port"] = str(int(config["smtp_port"]))
        for key in ("from_email", "from_name", "brand_name"):
            config[key] = clean_header(config[key], key)
        template = load_template(args.template)
        if args.send:
            validate_send_config(config)
    except (OSError, ValueError) as error:
        raise SystemExit(f"[configuration-error] {error}") from error

    with open(args.input, newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        fields = list(reader.fieldnames or [])
        if not fields:
            raise SystemExit("Input CSV has no header row.")
        rows = [{(key or "").strip(): (value or "").strip() for key, value in raw.items()} for raw in reader]

    output_fields = fields + [field for field in ADDED_QUEUE_FIELDS if field not in fields]
    logs: list[dict[str, str]] = []
    selected = 0
    skipped = 0
    for row in rows:
        review_status = row.get("review_status", "").strip().lower()
        outreach_status = row.get("outreach_status", "").strip().lower()
        email = row.get("primary_email", "").strip()
        eligible = review_status == "approved" and outreach_status in ALLOWED_STATUSES and is_email(email)
        if not eligible or selected >= args.max_send:
            skipped += 1
            continue

        selected += 1
        timestamp = utc_now()
        subject = (row.get("ai_subject") or "").strip() or render_text(args.subject, row, config)
        body = email_body(template, row, config)
        if not args.send:
            row["outreach_status"] = "dry_run_ready"
            row["last_outreach_at"] = timestamp
            row["last_outreach_error"] = ""
            logs.append({"candidate_id": row.get("candidate_id", ""), "email": email, "event": "dry_run_ready", "timestamp": timestamp, "details": subject})
            print(f"[dry-run] ready: {email} | {subject}")
            continue

        try:
            send_message(email, subject, body, config)
        except (OSError, smtplib.SMTPException, ValueError) as error:
            row["outreach_status"] = "failed"
            row["last_outreach_at"] = timestamp
            row["last_outreach_error"] = str(error)
            logs.append({"candidate_id": row.get("candidate_id", ""), "email": email, "event": "failed", "timestamp": timestamp, "details": str(error)})
            print(f"[failed] {email}: {error}", file=sys.stderr)
            continue

        row["outreach_status"] = "sent"
        row["first_contact_at"] = row.get("first_contact_at", "") or timestamp
        row["last_outreach_at"] = timestamp
        row["last_outreach_error"] = ""
        logs.append({"candidate_id": row.get("candidate_id", ""), "email": email, "event": "sent", "timestamp": timestamp, "details": subject})
        print(f"[sent] {email} | {subject}")
        if selected < args.max_send and args.pause:
            time.sleep(args.pause)

    write_csv(args.out, output_fields, rows)
    write_csv(args.log, LOG_FIELDS, logs)
    mode = "sent" if args.send else "dry-run ready"
    print(f"[done] {mode}={selected} skipped={skipped} queue={args.out} log={args.log}")


if __name__ == "__main__":
    main()
