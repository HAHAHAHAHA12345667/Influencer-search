#!/usr/bin/env python3
"""Enrich an existing creator CSV with public business-contact information.

This is useful when discovery has already happened and only the public contact
paths need another pass. It never attempts to bypass login, CAPTCHA, or email
reveal screens.
"""

from __future__ import annotations

import argparse
import csv

from youtube_influencer_mvp import (
    extract_emails,
    first_value,
    join_unique_values,
    merge_url_fields,
    scrape_public_contact_pages,
)


EXTRA_FIELDS = [
    "email",
    "emails",
    "email_source",
    "contact_urls",
    "contact_page_links",
    "contact_pages_checked",
    "contact_status",
]


def contact_status(emails: str, urls: str) -> str:
    if emails:
        return "email_found"
    if urls:
        return "contact_link_found"
    return "needs_manual_review"


def enrich_row(row: dict[str, str], pages: int, pause: float, skip_public_pages: bool) -> dict[str, str]:
    existing_emails = join_unique_values(
        extract_emails(row.get("emails", "")),
        extract_emails(row.get("email", "")),
        extract_emails(row.get("description", "")),
        extract_emails(row.get("bio", "")),
    )
    initial_urls = merge_url_fields(
        row.get("contact_urls", ""),
        row.get("about_links", ""),
        row.get("website", ""),
        row.get("external_url", ""),
        row.get("link_in_bio", ""),
    )
    page_emails = ""
    page_links = ""
    checked_pages = ""

    if initial_urls and not skip_public_pages:
        page_emails, page_links, checked_pages = scrape_public_contact_pages(
            initial_urls=initial_urls,
            max_pages=pages,
            pause_seconds=pause,
        )

    emails = join_unique_values(existing_emails, page_emails)
    row["email"] = first_value(emails)
    row["emails"] = emails
    row["email_source"] = (
        "existing_export + public_contact_page"
        if existing_emails and page_emails
        else "existing_export"
        if existing_emails
        else "public_contact_page"
        if page_emails
        else ""
    )
    row["contact_urls"] = merge_url_fields(initial_urls, page_links)
    row["contact_page_links"] = page_links
    row["contact_pages_checked"] = checked_pages
    row["contact_status"] = contact_status(emails, row["contact_urls"])
    return row


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find public business-contact paths from an existing creator CSV.")
    parser.add_argument("--input", required=True, help="Existing YouTube, TikTok, or Instagram candidate CSV.")
    parser.add_argument("--out", default="creator_contacts_enriched.csv")
    parser.add_argument("--contact-pages-per-creator", type=int, default=3)
    parser.add_argument("--pause", type=float, default=1.0)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument(
        "--skip-public-pages",
        action="store_true",
        help="Only normalize contact fields already present in the CSV; do not visit public links.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with open(args.input, newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        fieldnames = list(reader.fieldnames or [])
        rows = [
            enrich_row(
                {(key or ""): (value or "") for key, value in raw_row.items()},
                pages=max(1, args.contact_pages_per_creator),
                pause=args.pause,
                skip_public_pages=args.skip_public_pages,
            )
            for raw_row in list(reader)[: args.limit]
        ]

    output_fields = fieldnames + [field for field in EXTRA_FIELDS if field not in fieldnames]
    with open(args.out, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=output_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    emails_found = sum(bool(row.get("emails")) for row in rows)
    public_pages_checked = sum(bool(row.get("contact_pages_checked")) for row in rows)
    print(
        f"[done] saved {len(rows)} rows to {args.out} "
        f"(emails_found={emails_found}, public_pages_checked={public_pages_checked})"
    )


if __name__ == "__main__":
    main()
