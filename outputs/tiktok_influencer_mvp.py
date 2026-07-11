#!/usr/bin/env python3
"""Discover TikTok creators with Modash, then enrich public contact paths.

Setup in outputs/.env:
  MODASH_API_KEY=your_modash_discovery_api_key

Examples:
  python3 tiktok_influencer_mvp.py --keyword "gut health" --min-followers 10000 --limit 30
  python3 tiktok_influencer_mvp.py --keyword nutrition --keyword wellness --pages 3 --scrape-public-contact-pages

The script uses Modash for creator discovery, not a direct TikTok scraper. It
only follows public creator-supplied external links for contact enrichment.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from youtube_influencer_mvp import (
    extract_contact_urls,
    extract_emails,
    first_value,
    join_unique_values,
    merge_url_fields,
    scrape_public_contact_pages,
)


MODASH_TIKTOK_SEARCH_URL = "https://api.modash.io/v1/tiktok/search"
DEFAULT_KEYWORDS = ["gut health", "nutrition", "wellness", "fitness"]
HEALTH_TERMS = ("health", "wellness", "nutrition", "fitness", "dietitian", "doctor", "gut", "hormone")
BUSINESS_TERMS = ("business", "inquir", "collab", "partnership", "sponsor", "booking")


@dataclass
class TikTokCandidate:
    platform: str
    user_id: str
    profile_url: str
    handle: str
    display_name: str
    bio: str
    follower_count: str
    following_count: str
    likes_count: str
    video_count: str
    engagement_rate: str
    country: str
    language: str
    email: str
    emails: str
    email_source: str
    contact_urls: str
    contact_page_links: str
    contact_pages_checked: str
    contact_status: str
    discovery_keywords: str
    fit_score: int
    source: str
    collected_at: str


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


def load_modash_key(api_key_arg: str) -> str:
    dotenv = read_dotenv()
    key = api_key_arg.strip() or os.getenv("MODASH_API_KEY", "").strip() or dotenv.get("MODASH_API_KEY", "")
    if not key:
        raise SystemExit("Missing MODASH_API_KEY. Add it to outputs/.env or pass --api-key.")
    return key


def dig(value: dict[str, Any], *paths: str) -> Any:
    for path in paths:
        current: Any = value
        found = True
        for key in path.split("."):
            if not isinstance(current, dict) or key not in current:
                found = False
                break
            current = current[key]
        if found and current not in (None, ""):
            return current
    return ""


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def profile_url(handle: str, url: str) -> str:
    if url:
        return url
    return f"https://www.tiktok.com/@{handle.lstrip('@')}" if handle else ""


def int_or_none(value: str) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def contact_status(emails: str, urls: str) -> str:
    if emails:
        return "email_found"
    if urls:
        return "contact_link_found"
    return "needs_manual_review"


def score_candidate(candidate: TikTokCandidate) -> int:
    text = f"{candidate.display_name} {candidate.bio} {candidate.discovery_keywords}".lower()
    score = sum(8 for term in HEALTH_TERMS if term in text)
    score += sum(7 for term in BUSINESS_TERMS if term in text)
    if candidate.emails:
        score += 22
    followers = int_or_none(candidate.follower_count)
    if followers is not None:
        if 10_000 <= followers <= 500_000:
            score += 18
        elif 500_000 < followers <= 2_000_000:
            score += 10
    return min(score, 100)


def response_profiles(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("lookalikes", "result", "results", "influencers", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            for nested_key in ("lookalikes", "result", "results", "influencers", "items"):
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    return [item for item in nested if isinstance(item, dict)]
    return []


def normalize_profile(raw: dict[str, Any], keywords: list[str]) -> TikTokCandidate:
    profile = raw.get("profile") if isinstance(raw.get("profile"), dict) else raw
    handle = as_text(dig(profile, "username", "handle", "userName", "uniqueId"))
    if handle and not handle.startswith("@"):
        handle = f"@{handle}"
    bio = as_text(dig(profile, "description", "bio", "biography"))
    external_url = as_text(dig(profile, "externalUrl", "external_url", "website", "linkInBio"))
    urls = merge_url_fields(extract_contact_urls(bio), external_url)
    emails = join_unique_values(extract_emails(bio))
    candidate = TikTokCandidate(
        platform="tiktok",
        user_id=as_text(dig(raw, "userId", "id", "profile.userId", "profile.id")),
        profile_url=profile_url(handle, as_text(dig(profile, "url", "profileUrl", "profile_url"))),
        handle=handle,
        display_name=as_text(dig(profile, "fullName", "displayName", "name", "nickname")),
        bio=bio,
        follower_count=as_text(dig(profile, "followers", "followersCount", "followers_count")),
        following_count=as_text(dig(profile, "following", "followingCount", "following_count")),
        likes_count=as_text(dig(profile, "likes", "likesCount", "totalLikes", "likes_count")),
        video_count=as_text(dig(profile, "posts", "videos", "videoCount", "video_count")),
        engagement_rate=as_text(dig(raw, "engagementRate", "engagement_rate", "profile.engagementRate")),
        country=as_text(dig(profile, "country", "location.country", "countryCode")),
        language=as_text(dig(profile, "language", "languages.0")),
        email=first_value(emails),
        emails=emails,
        email_source="bio" if emails else "",
        contact_urls=urls,
        contact_page_links="",
        contact_pages_checked="",
        contact_status=contact_status(emails, urls),
        discovery_keywords=" | ".join(keywords),
        fit_score=0,
        source="modash_discovery_api",
        collected_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )
    candidate.fit_score = score_candidate(candidate)
    return candidate


def build_filter(keywords: list[str], min_followers: int, max_followers: int, override: str) -> dict[str, Any]:
    if override:
        parsed = json.loads(override)
        if not isinstance(parsed, dict):
            raise ValueError("--filter-json must be a JSON object.")
        return parsed

    influencer: dict[str, Any] = {"relevance": keywords}
    if min_followers or max_followers:
        followers: dict[str, int] = {}
        if min_followers:
            followers["min"] = min_followers
        if max_followers:
            followers["max"] = max_followers
        influencer["followers"] = followers
    return {"influencer": influencer}


def search_modash(api_key: str, request_body: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(
        MODASH_TIKTOK_SEARCH_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=request_body,
        timeout=45,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("error"):
        raise RuntimeError(as_text(payload))
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Automatically find TikTok health/wellness creators using Modash.")
    parser.add_argument("--api-key", default="", help="Modash API key. Prefer MODASH_API_KEY in outputs/.env.")
    parser.add_argument("--keyword", dest="keywords", action="append", help="Repeat for several health topics.")
    parser.add_argument("--min-followers", type=int, default=10_000)
    parser.add_argument("--max-followers", type=int, default=0)
    parser.add_argument("--pages", type=int, default=1, help="Modash search pages; up to 15 results per page.")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--pause", type=float, default=1.0)
    parser.add_argument(
        "--filter-json",
        default="",
        help="Optional complete Modash filter object for advanced filters such as audience geography.",
    )
    parser.add_argument("--scrape-public-contact-pages", action="store_true")
    parser.add_argument("--contact-pages-per-creator", type=int, default=3)
    parser.add_argument("--out-csv", default="tiktok_influencer_candidates.csv")
    parser.add_argument("--out-json", default="tiktok_influencer_candidates.json")
    parser.add_argument("--dry-run", action="store_true", help="Print the API request body without calling Modash.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    keywords = args.keywords or DEFAULT_KEYWORDS
    try:
        filter_object = build_filter(keywords, args.min_followers, args.max_followers, args.filter_json)
    except (ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Invalid filter: {exc}") from exc

    base_body = {"sort": {"field": "followers", "direction": "desc"}, "filter": filter_object}
    if args.dry_run:
        print(json.dumps(base_body, ensure_ascii=False, indent=2))
        return

    api_key = load_modash_key(args.api_key)
    candidates: list[TikTokCandidate] = []
    seen: set[str] = set()

    for page in range(args.pages):
        body = {**base_body, "page": page}
        print(f"[search:modash] tiktok page={page + 1} keywords={', '.join(keywords)}")
        try:
            payload = search_modash(api_key, body)
        except requests.RequestException as exc:
            print(f"[api-error] Modash request failed: {exc}", file=sys.stderr)
            break
        except RuntimeError as exc:
            print(f"[api-error] Modash returned: {exc}", file=sys.stderr)
            break

        profiles = response_profiles(payload)
        if not profiles:
            print("[search:modash] no profiles returned")
            break

        for raw in profiles:
            candidate = normalize_profile(raw, keywords)
            unique_key = (candidate.user_id or candidate.profile_url or candidate.handle).lower()
            if not unique_key or unique_key in seen:
                continue
            seen.add(unique_key)

            if args.scrape_public_contact_pages and candidate.contact_urls:
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
                    candidate.email_source = "bio + public_contact_page" if candidate.email_source else "public_contact_page"
                candidate.contact_urls = merge_url_fields(candidate.contact_urls, page_links)
                candidate.contact_status = contact_status(candidate.emails, candidate.contact_urls)
                candidate.fit_score = score_candidate(candidate)

            candidates.append(candidate)
            if len(candidates) >= args.limit:
                break

        if len(candidates) >= args.limit:
            break
        time.sleep(args.pause)

    candidates.sort(key=lambda row: row.fit_score, reverse=True)
    fields = list(TikTokCandidate.__dataclass_fields__)
    with open(args.out_csv, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(asdict(row) for row in candidates)
    with open(args.out_json, "w", encoding="utf-8") as file:
        json.dump([asdict(row) for row in candidates], file, ensure_ascii=False, indent=2)
    email_count = sum(bool(row.emails) for row in candidates)
    print(f"[done] saved {len(candidates)} TikTok creators to {args.out_csv} and {args.out_json} (emails_found={email_count})")


if __name__ == "__main__":
    main()
