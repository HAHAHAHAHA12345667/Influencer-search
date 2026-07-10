#!/usr/bin/env python3
"""Turn reviewed creator candidates into one consistent outreach queue.

This tool does not send messages. It creates a compact CSV for a human to
approve before any email or DM is sent.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
from datetime import UTC, datetime


OUTPUT_FIELDS = [
    "candidate_id",
    "platform",
    "creator_name",
    "handle",
    "profile_url",
    "primary_email",
    "all_emails",
    "contact_method",
    "contact_status",
    "audience_size",
    "fit_score",
    "niche_or_topics",
    "source_file",
    "review_status",
    "outreach_status",
    "owner",
    "campaign_angle",
    "personalization_note",
    "first_contact_at",
    "follow_up_at",
    "notes",
    "created_at",
]


def first_value(value: str) -> str:
    return value.split("|", 1)[0].strip() if value else ""


def get_value(row: dict[str, str], *names: str) -> str:
    for name in names:
        value = (row.get(name) or "").strip()
        if value:
            return value
    return ""


def candidate_id(platform: str, profile_url: str, handle: str, email: str) -> str:
    seed = "|".join([platform.lower(), profile_url.lower(), handle.lower(), email.lower()])
    return f"creator_{hashlib.sha1(seed.encode()).hexdigest()[:12]}"


def to_queue_row(raw: dict[str, str], source_file: str) -> dict[str, str]:
    platform = get_value(raw, "platform")
    profile_url = get_value(raw, "profile_url", "handle_url", "channel_url")
    handle = get_value(raw, "handle")
    all_emails = get_value(raw, "emails", "email")
    primary_email = first_value(all_emails)
    contact_method = "email" if primary_email else "manual_profile_contact"
    audience_size = get_value(raw, "follower_count", "subscriber_count")
    niche_or_topics = get_value(raw, "niche", "topic_categories", "keywords", "discovery_query")

    return {
        "candidate_id": candidate_id(platform, profile_url, handle, primary_email),
        "platform": platform,
        "creator_name": get_value(raw, "display_name", "title"),
        "handle": handle,
        "profile_url": profile_url,
        "primary_email": primary_email,
        "all_emails": all_emails,
        "contact_method": contact_method,
        "contact_status": get_value(raw, "contact_status") or "needs_manual_review",
        "audience_size": audience_size,
        "fit_score": get_value(raw, "fit_score"),
        "niche_or_topics": niche_or_topics,
        "source_file": source_file,
        "review_status": "to_review",
        "outreach_status": "not_started",
        "owner": "",
        "campaign_angle": "",
        "personalization_note": "",
        "first_contact_at": "",
        "follow_up_at": "",
        "notes": "",
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a human-review outreach queue from creator candidates.")
    parser.add_argument("--input", required=True, help="YouTube or short-video candidate CSV.")
    parser.add_argument("--out", default="outreach_queue.csv", help="Output CSV path.")
    parser.add_argument("--min-score", type=int, default=0, help="Keep candidates with this fit score or higher.")
    parser.add_argument("--include-no-email", action="store_true", help="Also include rows that require profile/DM contact.")
    parser.add_argument("--limit", type=int, default=100, help="Maximum rows to add to the queue.")
    return parser.parse_args()


def fit_score(row: dict[str, str]) -> int:
    try:
        return int(row["fit_score"] or 0)
    except ValueError:
        return 0


def main() -> None:
    args = parse_args()
    queue: list[dict[str, str]] = []
    seen: set[str] = set()

    with open(args.input, newline="", encoding="utf-8-sig") as file:
        for raw_row in csv.DictReader(file):
            row = {(key or "").strip(): (value or "").strip() for key, value in raw_row.items()}
            queue_row = to_queue_row(row, args.input)
            if fit_score(queue_row) < args.min_score:
                continue
            if not queue_row["primary_email"] and not args.include_no_email:
                continue
            if queue_row["candidate_id"] in seen:
                continue
            seen.add(queue_row["candidate_id"])
            queue.append(queue_row)
            if len(queue) >= args.limit:
                break

    queue.sort(key=fit_score, reverse=True)
    with open(args.out, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(queue)

    print(f"[done] saved {len(queue)} review rows to {args.out}")


if __name__ == "__main__":
    main()
