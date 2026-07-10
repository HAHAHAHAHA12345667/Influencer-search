#!/usr/bin/env python3
"""Enrich and filter TikTok/Instagram creator exports.

This script deliberately works from a creator list exported from an approved
source (for example a creator marketplace or licensed influencer-data provider).
It does not bypass TikTok/Instagram sign-in, CAPTCHA, or private email screens.

Examples:
  python3 short_video_influencer_mvp.py --input short_video_input_template.csv --scrape-public-contact-pages
  python3 short_video_influencer_mvp.py --input creators.csv --platform tiktok --min-followers 10000 --require-email
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from youtube_influencer_mvp import (
    clean_text,
    extract_contact_urls,
    extract_emails,
    first_value,
    join_unique_values,
    merge_url_fields,
    scrape_public_contact_pages,
)


HEALTH_TERMS = (
    "health",
    "wellness",
    "nutrition",
    "fitness",
    "dietitian",
    "doctor",
    "gut",
    "hormone",
    "mental health",
    "healthy",
)
BUSINESS_TERMS = ("business", "inquir", "collab", "partnership", "sponsor", "booking", "email")
COUNT_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([kmbä¸äº¿]?)\s*$", re.IGNORECASE)


@dataclass
class ShortVideoCandidate:
    platform: str
    profile_url: str
    handle: str
    display_name: str
    bio: str
    follower_count: str
    following_count: str
    likes_count: str
    video_count: str
    email: str
    emails: str
    email_source: str
    contact_urls: str
    contact_page_links: str
    contact_pages_checked: str
    contact_status: str
    country: str
    language: str
    niche: str
    source: str
    fit_score: int
    collected_at: str


def pick(row: dict[str, str], *names: str) -> str:
    for name in names:
        value = row.get(name, "").strip()
        if value:
            return value
    return ""


def parse_count(value: str) -> int | None:
    compact = value.strip().lower().replace(",", "").replace(" ", "")
    if not compact:
        return None
    match = COUNT_RE.match(compact)
    if not match:
        return None
    number = float(match.group(1))
    suffix = match.group(2)
    multiplier = {"": 1, "k": 1_000, "m": 1_000_000, "b": 1_000_000_000, "ä¸": 10_000, "äº¿": 100_000_000}[suffix]
    return int(number * multiplier)


def normalize_platform(value: str) -> str:
    platform = value.strip().lower()
    aliases = {"ig": "instagram", "insta": "instagram", "tt": "tiktok", "tik tok": "tiktok"}
    return aliases.get(platform, platform)


def profile_url(platform: str, handle: str, input_url: str) -> str:
    if input_url:
        return input_url
    normalized_handle = handle.lstrip("@")
    if not normalized_handle:
        return ""
    if platform == "tiktok":
        return f"https://www.tiktok.com/@{normalized_handle}"
    if platform == "instagram":
        return f"https://www.instagram.com/{normalized_handle}/"
    return ""


def contact_status(emails: str, contact_urls: str) -> str:
    if emails:
        return "email_found"
    if contact_urls:
        return "contact_link_found"
    return "needs_manual_review"


def score_candidate(candidate: ShortVideoCandidate) -> int:
    searchable_text = f"{candidate.display_name} {candidate.bio} {candidate.niche}".lower()
    score = sum(8 for term in HEALTH_TERMS if term in searchable_text)
    score += sum(7 for term in BUSINESS_TERMS if term in searchable_text)
    if candidate.emails:
        score += 22
    followers = parse_count(candidate.follower_count)
    if followers is not None:
        if 10_000 <= followers <= 500_000:
            score += 18
        elif 500_000 < followers <= 2_000_000:
            score += 10
    return min(score, 100)


def row_to_candidate(row: dict[str, str]) -> ShortVideoCandidate:
    platform = normalize_platform(pick(row, "platform"))
    bio = pick(row, "bio", "description", "biography")
    raw_contact_urls = join_unique_values(
        extract_contact_urls(bio),
        pick(row, "external_url"),
        pick(row, "website"),
        pick(row, "link_in_bio"),
        pick(row, "contact_url"),
    )
    emails = join_unique_values(
        extract_emails(bio),
        extract_emails(pick(row, "email")),
        extract_emails(pick(row, "emails")),
    )
    handle = pick(row, "handle", "username", "user_name")
    candidate = ShortVideoCandidate(
        platform=platform,
        profile_url=profile_url(platform, handle, pick(row, "profile_url", "url", "channel_url")),
        handle=handle,
        display_name=clean_text(pick(row, "display_name", "name", "title"), allow_unicode=True),
        bio=clean_text(bio, allow_unicode=True),
        follower_count=pick(row, "follower_count", "followers", "followers_count"),
        following_count=pick(row, "following_count", "following"),
        likes_count=pick(row, "likes_count", "likes", "total_likes"),
        video_count=pick(row, "video_count", "videos", "posts_count"),
        email=first_value(emails),
        emails=emails,
        email_source="input_bio_or_export" if emails else "",
        contact_urls=raw_contact_urls,
        contact_page_links="",
        contact_pages_checked="",
        contact_status=contact_status(emails, raw_contact_urls),
        country=pick(row, "country", "region"),
        language=pick(row, "language"),
        niche=pick(row, "niche", "category", "topic"),
        source=pick(row, "source") or "creator_export",
        fit_score=0,
        collected_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )
    candidate.fit_score = score_candidate(candidate)
    return candidate


def passes_filters(candidate: ShortVideoCandidate, args: argparse.Namespace) -> bool:
    if args.platform and candidate.platform != args.platform:
        return False
    followers = parse_count(candidate.follower_count)
    if args.min_followers and (followers is None or followers < args.min_followers):
        return False
    if args.max_followers and (followers is None or followers > args.max_followers):
        return False
    if args.require_email and not candidate.emails:
        return False
    return bool(candidate.profile_url or candidate.handle)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enrich approved TikTok/Instagram creator exports.")
    parser.add_argument("--input", required=True, help="CSV exported from a creator source.")
    parser.add_argument("--platform", choices=["tiktok", "instagram"], help="Keep one platform only.")
    parser.add_argument("--min-followers", type=int, default=0)
    parser.add_argument("--max-followers", type=int, default=0)
    parser.add_argument("--require-email", action="store_true", help="Keep only rows with a public email.")
    parser.add_argument(
        "--scrape-public-contact-pages",
        action="store_true",
        help="Scan public bio/website/Linktree pages for publicly displayed business emails.",
    )
    parser.add_argument("--contact-pages-per-creator", type=int, default=3)
    parser.add_argument("--pause", type=float, default=1.0)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--out-csv", default="short_video_influencer_candidates.csv")
    parser.add_argument("--out-json", default="short_video_influencer_candidates.json")
    return parser.parse_args()


def save_csv(path: str, rows: list[ShortVideoCandidate]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=list(ShortVideoCandidate.__dataclass_fields__))
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def main() -> None:
    args = parse_args()
    candidates: list[ShortVideoCandidate] = []
    seen_profiles: set[str] = set()

    with open(args.input, newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        for raw_row in reader:
            row = {(key or "").strip().lower(): (value or "").strip() for key, value in raw_row.items()}
            candidate = row_to_candidate(row)
            unique_key = (candidate.profile_url or f"{candidate.platform}:{candidate.handle}").lower()
            if unique_key in seen_profiles:
                continue
            seen_profiles.add(unique_key)

            if args.scrape_public_contact_pages:
                page_emails, page_links, checked_pages = scrape_public_contact_pages(
                    initial_urls=candidate.contact_urls,
                    max_pages=max(1, args.contact_pages_per_creator),
                    pause_seconds=args.pause,
                )
                candidate.contact_page_links = page_links
                candidate.contact_pages_checked = checked_pages
                candidate.emails = join_unique_values(candidate.emails, page_emails)
                candidate.email = first_value(candidate.emails)
                if page_emails:
                    candidate.email_source = (
                        "input_bio_or_export + public_contact_page"
                        if candidate.email_source
                        else "public_contact_page"
                    )
                candidate.contact_urls = merge_url_fields(candidate.contact_urls, page_links)
                candidate.contact_status = contact_status(candidate.emails, candidate.contact_urls)
                candidate.fit_score = score_candidate(candidate)

            if passes_filters(candidate, args):
                candidates.append(candidate)
            if len(candidates) >= args.limit:
                break

    candidates.sort(key=lambda candidate: candidate.fit_score, reverse=True)
    save_csv(args.out_csv, candidates)
    with open(args.out_json, "w", encoding="utf-8") as file:
        json.dump([asdict(candidate) for candidate in candidates], file, ensure_ascii=False, indent=2)
    print(f"[done] saved {len(candidates)} candidates to {args.out_csv} and {args.out_json}")


if __name__ == "__main__":
    main()
