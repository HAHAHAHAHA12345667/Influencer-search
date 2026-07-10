#!/usr/bin/env python3
"""
YouTube influencer discovery MVP.

This uses the official YouTube Data API v3:
  1. search.list finds channel IDs.
  2. channels.list enriches each channel with snippet/statistics/branding data.

Setup:
  export YOUTUBE_API_KEY="your_youtube_data_api_key"

Or add this to .env next to the script:
  YOUTUBE_API_KEY=your_youtube_data_api_key

Examples:
  python3 youtube_influencer_mvp.py --mode topic --pages 2 --min-subs 10000
  python3 youtube_influencer_mvp.py --mode keyword --keyword nutrition --keyword "gut health"
  python3 youtube_influencer_mvp.py --mode both --keyword wellness --pages 3 --limit 200
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Iterable
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests


YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
DEFAULT_HEALTH_TOPIC_ID = "/m/0kt51"
DEFAULT_KEYWORDS = [
    "gut health",
    "nutrition",
    "wellness",
    "fitness",
    "dietitian",
    "women's health",
]

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.IGNORECASE)
URL_RE = re.compile(
    r"(https?://[^\s\"'<>]+|(?:linktr\.ee|beacons\.ai|stan\.store|msha\.ke|hoo\.be|bio\.site|"
    r"taplink\.cc|campsite\.bio|solo\.to|flowcode\.com)/[^\s\"'<>]+)",
    re.IGNORECASE,
)
ABOUT_REDIRECT_RE = re.compile(
    r"(?:https?://(?:www\.)?youtube\.com)?/redirect\?[^\"'<>\\\s]+",
    re.IGNORECASE,
)
BIO_LINK_HOSTS = (
    "linktr.ee",
    "beacons.ai",
    "stan.store",
    "msha.ke",
    "hoo.be",
    "bio.site",
    "taplink.cc",
    "campsite.bio",
    "solo.to",
    "flowcode.com",
)
SOCIAL_HOSTS = (
    "instagram.com",
    "tiktok.com",
    "youtube.com",
    "facebook.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "pinterest.com",
)
CONTACT_PATH_RE = re.compile(r"(?:contact|about|booking|work-with|collab|partner|media|press)", re.IGNORECASE)
TEXT_REPLACEMENTS = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2022": "-",
        "\u2026": "...",
        "\u00a0": " ",
    }
)


@dataclass
class YouTubeCandidate:
    platform: str
    channel_id: str
    title: str
    handle: str
    channel_url: str
    handle_url: str
    description: str
    email: str
    emails: str
    email_source: str
    contact_urls: str
    about_links: str
    contact_page_links: str
    contact_pages_checked: str
    contact_status: str
    subscriber_count: str
    hidden_subscriber_count: str
    video_count: str
    view_count: str
    country: str
    published_at: str
    keywords: str
    topic_categories: str
    discovery_query: str
    fit_score: int
    collected_at: str


def read_dotenv() -> dict[str, str]:
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    values: dict[str, str] = {}

    if not os.path.exists(env_path):
        return values

    with open(env_path, encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")

    return values


def load_api_key(api_key_arg: str = "") -> str:
    dotenv = read_dotenv()
    api_key = (
        api_key_arg.strip()
        or os.getenv("YOUTUBE_API_KEY", "").strip()
        or dotenv.get("YOUTUBE_API_KEY", "").strip()
        or os.getenv("GOOGLE_API_KEY", "").strip()
        or dotenv.get("GOOGLE_API_KEY", "").strip()
    )

    if not api_key:
        raise SystemExit("Missing API key. Set YOUTUBE_API_KEY in your terminal or outputs/.env.")

    return api_key


def youtube_get(url: str, params: dict[str, object]) -> dict:
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.HTTPError as exc:
        response = exc.response
        print(f"[http-error] YouTube returned {response.status_code if response is not None else 'unknown'}", file=sys.stderr)
        if response is not None:
            print(response.text[:1500], file=sys.stderr)
        return {}
    except requests.RequestException as exc:
        print(f"[network-error] {exc}", file=sys.stderr)
        return {}


def build_discovery_queries(mode: str, keywords: list[str]) -> Iterable[tuple[str, str]]:
    if mode in {"topic", "both"}:
        yield "topic", ""

    if mode in {"keyword", "both"}:
        for keyword in keywords:
            yield "keyword", keyword


def search_channel_ids(
    api_key: str,
    query: str,
    pages: int,
    topic_id: str,
    region: str,
    language: str,
    pause_seconds: float,
) -> Iterable[tuple[str, str]]:
    page_token = ""

    for _ in range(pages):
        params: dict[str, object] = {
            "key": api_key,
            "part": "snippet",
            "type": "channel",
            "maxResults": 50,
            "safeSearch": "moderate",
            "order": "relevance",
        }

        if query:
            params["q"] = query
        else:
            params["topicId"] = topic_id

        if region:
            params["regionCode"] = region
        if language:
            params["relevanceLanguage"] = language
        if page_token:
            params["pageToken"] = page_token

        payload = youtube_get(YOUTUBE_SEARCH_URL, params)
        items = payload.get("items", [])
        if not items:
            break

        discovery_query = query or f"topic:{topic_id}"
        for item in items:
            channel_id = item.get("id", {}).get("channelId", "")
            if channel_id:
                yield channel_id, discovery_query

        page_token = payload.get("nextPageToken", "")
        if not page_token:
            break

        time.sleep(pause_seconds)


def chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def fetch_channels(api_key: str, channel_ids: list[str], pause_seconds: float) -> Iterable[dict]:
    for batch in chunks(channel_ids, 50):
        params = {
            "key": api_key,
            "part": "snippet,statistics,brandingSettings,topicDetails",
            "id": ",".join(batch),
            "maxResults": 50,
        }
        payload = youtube_get(YOUTUBE_CHANNELS_URL, params)
        yield from payload.get("items", [])
        time.sleep(pause_seconds)


def extract_emails(text: str) -> list[str]:
    emails: list[str] = []
    seen: set[str] = set()

    for match in EMAIL_RE.findall(html.unescape(text or "")):
        email = match.lower().rstrip(".,;:)")
        if email and email not in seen:
            seen.add(email)
            emails.append(email)

    return emails


def join_unique_values(*fields: str | list[str]) -> str:
    values: list[str] = []
    seen: set[str] = set()

    for field in fields:
        parts = field if isinstance(field, list) else field.split("|")
        for raw_value in parts:
            value = raw_value.strip()
            key = value.lower()
            if value and key not in seen:
                seen.add(key)
                values.append(value)

    return " | ".join(values)


def first_value(field: str) -> str:
    return field.split("|", 1)[0].strip() if field else ""


def normalize_url(url: str) -> str:
    url = url.strip().rstrip(".,;)")
    if not url:
        return ""
    if not url.startswith("http"):
        url = f"https://{url}"

    parsed = urlparse(url)
    if not parsed.netloc:
        return ""

    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc.lower()}{path}"


def extract_contact_urls(text: str) -> str:
    urls: list[str] = []
    seen: set[str] = set()

    for raw_url in URL_RE.findall(text):
        normalized = normalize_url(raw_url)
        if normalized and normalized not in seen:
            seen.add(normalized)
            urls.append(normalized)

    return " | ".join(urls)


class PublicPageParser(HTMLParser):
    """Collect visible text and link targets from one public contact page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(href)

    def handle_data(self, data: str) -> None:
        self.text_parts.append(data)


def host_matches(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


def is_bio_link(url: str) -> bool:
    return host_matches(urlparse(url).netloc.lower().removeprefix("www."), BIO_LINK_HOSTS)


def is_social_link(url: str) -> bool:
    return host_matches(urlparse(url).netloc.lower().removeprefix("www."), SOCIAL_HOSTS)


def is_crawlable_contact_url(url: str) -> bool:
    parsed = urlparse(url)
    return bool(parsed.scheme in {"http", "https"} and parsed.netloc and not is_social_link(url))


def normalize_page_link(raw_url: str, base_url: str) -> str:
    raw_url = html.unescape(raw_url.strip())
    if raw_url.startswith("mailto:"):
        return raw_url
    return normalize_url(urljoin(base_url, raw_url))


def scrape_public_contact_pages(
    initial_urls: str,
    max_pages: int,
    pause_seconds: float,
) -> tuple[str, str, str]:
    """Extract emails and useful links from public creator-owned contact pages.

    The crawler is deliberately small: it starts from links supplied by the
    creator, follows a Linktree-style page, and may inspect same-site pages whose
    URL clearly indicates contact/about/booking. It never attempts to bypass
    logins, CAPTCHA, or platform email-reveal screens.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    pending = [
        normalized
        for raw_url in initial_urls.split("|")
        if (normalized := normalize_url(raw_url.strip())) and is_crawlable_contact_url(normalized)
    ]
    emails: list[str] = []
    page_links: list[str] = []
    checked_pages: list[str] = []
    seen_pages: set[str] = set()
    seen_emails: set[str] = set()
    seen_links: set[str] = set()

    while pending and len(checked_pages) < max_pages:
        page_url = pending.pop(0)
        if page_url in seen_pages:
            continue
        seen_pages.add(page_url)

        try:
            response = requests.get(page_url, headers=headers, timeout=30, allow_redirects=True)
            final_url = normalize_url(response.url) or page_url
            checked_pages.append(final_url)
            if response.status_code != 200:
                print(f"[contact-page-warn] {final_url}: status={response.status_code}", file=sys.stderr)
                continue

            content_type = response.headers.get("content-type", "").lower()
            if content_type and "html" not in content_type:
                continue

            parser = PublicPageParser()
            parser.feed(response.text)
            page_text = " ".join(parser.text_parts)
            page_emails = extract_emails(response.text + " " + page_text)
            for email in page_emails:
                if email not in seen_emails:
                    seen_emails.add(email)
                    emails.append(email)

            discovered: list[str] = []
            for raw_link in parser.links:
                normalized = normalize_page_link(raw_link, response.url)
                if normalized.startswith("mailto:"):
                    for email in extract_emails(normalized):
                        if email not in seen_emails:
                            seen_emails.add(email)
                            emails.append(email)
                    continue
                if normalized and normalized not in seen_links and is_useful_about_link(normalized):
                    seen_links.add(normalized)
                    page_links.append(normalized)
                    discovered.append(normalized)

            current_host = urlparse(final_url).netloc.lower().removeprefix("www.")
            for discovered_url in discovered:
                discovered_host = urlparse(discovered_url).netloc.lower().removeprefix("www.")
                is_same_site_contact = discovered_host == current_host and bool(CONTACT_PATH_RE.search(discovered_url))
                if (
                    is_crawlable_contact_url(discovered_url)
                    and discovered_url not in seen_pages
                    and (is_bio_link(final_url) or is_same_site_contact)
                ):
                    pending.append(discovered_url)

            if pending and len(checked_pages) < max_pages:
                time.sleep(pause_seconds)
        except requests.RequestException as exc:
            print(f"[contact-page-error] {page_url}: {exc}", file=sys.stderr)

    return " | ".join(emails), " | ".join(page_links), " | ".join(checked_pages)


def clean_youtube_html(text: str) -> str:
    return (
        html.unescape(text)
        .replace("\\u0026", "&")
        .replace("\\u003d", "=")
        .replace("\\/", "/")
    )


def decode_youtube_redirect(url: str) -> str:
    url = clean_youtube_html(url.strip())

    if url.startswith("/redirect?"):
        url = "https://www.youtube.com" + url

    parsed = urlparse(url)
    if "youtube.com" in parsed.netloc and parsed.path == "/redirect":
        query = parse_qs(parsed.query)
        target = query.get("q") or query.get("u")
        if target:
            return unquote(target[0])

    return url


def is_useful_about_link(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")

    blocked_hosts = (
        "google.com",
        "gstatic.com",
        "ytimg.com",
        "googleusercontent.com",
        "youtubei.googleapis.com",
    )

    if not parsed.scheme.startswith("http"):
        return False
    if any(host == blocked_host or host.endswith(f".{blocked_host}") for blocked_host in blocked_hosts):
        return False

    return True


def merge_url_fields(*fields: str) -> str:
    urls: list[str] = []
    seen: set[str] = set()

    for field in fields:
        if not field:
            continue

        for raw_url in field.split("|"):
            normalized = normalize_url(raw_url.strip())
            if normalized and normalized not in seen:
                seen.add(normalized)
                urls.append(normalized)

    return " | ".join(urls)


def scrape_about_links(handle_url: str, channel_url: str, pause_seconds: float = 1.5) -> str:
    """Scrape public external links from a YouTube channel About page.

    YouTube Data API does not expose the About-page link block directly, so this
    function extracts YouTube redirect URLs from the public page HTML and decodes
    their q/u target parameters. This is best-effort and may need updates if
    YouTube changes its page structure.
    """
    about_pages: list[str] = []

    for base_url in [handle_url, channel_url]:
        if base_url:
            about_pages.append(base_url.rstrip("/") + "/about")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    links: list[str] = []
    seen: set[str] = set()

    for about_url in about_pages:
        try:
            response = requests.get(about_url, headers=headers, timeout=30)
            if response.status_code != 200:
                print(f"[about-link-warn] {about_url}: status={response.status_code}", file=sys.stderr)
                continue

            text = clean_youtube_html(response.text)

            for raw_url in ABOUT_REDIRECT_RE.findall(text):
                decoded = decode_youtube_redirect(raw_url)
                normalized = normalize_url(decoded)

                if normalized and is_useful_about_link(normalized) and normalized not in seen:
                    seen.add(normalized)
                    links.append(normalized)

            if links:
                break

            time.sleep(pause_seconds)

        except requests.RequestException as exc:
            print(f"[about-link-error] {about_url}: {exc}", file=sys.stderr)

    return " | ".join(links)


def contact_status(emails: str, contact_urls: str) -> str:
    if emails:
        return "email_found"
    if contact_urls:
        return "contact_link_found"
    return "needs_manual_review"


def int_or_none(value: str) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def clean_text(text: str, allow_unicode: bool = False) -> str:
    if not text:
        return ""

    text = unicodedata.normalize("NFKC", text)
    text = text.translate(TEXT_REPLACEMENTS)
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = re.sub(r"\s+", " ", text).strip()

    if allow_unicode:
        return text

    cleaned_chars: list[str] = []
    for char in text:
        if char.isascii():
            cleaned_chars.append(char)
            continue

        category = unicodedata.category(char)
        if category.startswith(("S", "C")):
            continue

        ascii_fallback = unicodedata.normalize("NFKD", char).encode("ascii", "ignore").decode("ascii")
        if ascii_fallback:
            cleaned_chars.append(ascii_fallback)

    return re.sub(r"\s+", " ", "".join(cleaned_chars)).strip()


def score_channel(title: str, description: str, keywords: str, email: str, subs: int | None) -> int:
    text = f"{title} {description} {keywords}".lower()
    score = 0

    for term in [
        "health",
        "wellness",
        "nutrition",
        "fitness",
        "dietitian",
        "doctor",
        "gut",
        "hormone",
        "mental health",
    ]:
        if term in text:
            score += 8

    for signal in ["business", "inquiries", "collab", "partnership", "sponsor"]:
        if signal in text:
            score += 8

    if email:
        score += 22
    if subs is not None:
        if 10_000 <= subs <= 500_000:
            score += 18
        elif 500_000 < subs <= 2_000_000:
            score += 10

    return min(score, 100)


def channel_to_candidate(
    item: dict,
    discovery_query: str,
    clean_output_text: bool = True,
) -> YouTubeCandidate:
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    branding = item.get("brandingSettings", {}).get("channel", {})
    topics = item.get("topicDetails", {}).get("topicCategories", [])

    channel_id = item.get("id", "")
    title = snippet.get("title", "")
    description = snippet.get("description", "")
    handle = snippet.get("customUrl", "")
    if handle and not handle.startswith("@"):
        handle = f"@{handle}"

    keywords = branding.get("keywords", "")
    country = snippet.get("country", "") or branding.get("country", "")
    emails = join_unique_values(extract_emails(description))
    email = first_value(emails)
    contact_urls = extract_contact_urls(description)
    subscriber_count = stats.get("subscriberCount", "")
    subs_int = int_or_none(subscriber_count)

    output_title = clean_text(title, allow_unicode=not clean_output_text)
    output_description = clean_text(description, allow_unicode=not clean_output_text)
    output_keywords = clean_text(keywords, allow_unicode=not clean_output_text)

    return YouTubeCandidate(
        platform="youtube",
        channel_id=channel_id,
        title=output_title,
        handle=handle,
        channel_url=f"https://www.youtube.com/channel/{channel_id}",
        handle_url=f"https://www.youtube.com/{handle}" if handle else "",
        description=output_description,
        email=email,
        emails=emails,
        email_source="description" if email else "",
        contact_urls=contact_urls,
        about_links="",
        contact_page_links="",
        contact_pages_checked="",
        contact_status=contact_status(email, contact_urls),
        subscriber_count=subscriber_count,
        hidden_subscriber_count=str(stats.get("hiddenSubscriberCount", "")),
        video_count=stats.get("videoCount", ""),
        view_count=stats.get("viewCount", ""),
        country=country,
        published_at=snippet.get("publishedAt", ""),
        keywords=output_keywords,
        topic_categories=" | ".join(topics),
        discovery_query=discovery_query,
        fit_score=score_channel(title, description, keywords, email, subs_int),
        collected_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )


def passes_filters(
    candidate: YouTubeCandidate,
    min_subs: int,
    max_subs: int,
    include_hidden_subs: bool,
) -> bool:
    subs = int_or_none(candidate.subscriber_count)
    if subs is None:
        return include_hidden_subs
    if min_subs and subs < min_subs:
        return False
    if max_subs and subs > max_subs:
        return False
    return True


def save_csv(path: str, rows: list[YouTubeCandidate]) -> None:
    fieldnames = list(YouTubeCandidate.__dataclass_fields__)
    with open(path, "w", newline="", encoding="utf-8-sig") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def save_json(path: str, rows: list[YouTubeCandidate]) -> None:
    with open(path, "w", encoding="utf-8") as jsonfile:
        json.dump([asdict(row) for row in rows], jsonfile, ensure_ascii=False, indent=2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find YouTube health/wellness creator channels.")
    parser.add_argument("--api-key", default="", help="YouTube Data API key.")
    parser.add_argument(
        "--mode",
        choices=["topic", "keyword", "both"],
        default="topic",
        help="Discovery mode. topic does not require keywords.",
    )
    parser.add_argument("--keyword", action="append", dest="keywords", help="Repeat for multiple keywords.")
    parser.add_argument("--topic-id", default=DEFAULT_HEALTH_TOPIC_ID, help="YouTube topic ID. Default is Health.")
    parser.add_argument("--region", default="US", help="Region code, e.g. US, CA, GB.")
    parser.add_argument("--language", default="en", help="Relevance language, e.g. en.")
    parser.add_argument("--pages", type=int, default=1, help="Search pages per discovery query.")
    parser.add_argument("--pause", type=float, default=0.8, help="Delay between API calls.")
    parser.add_argument(
        "--scrape-about-links",
        action="store_true",
        help="Also scrape public external links from each channel About page.",
    )
    parser.add_argument(
        "--scrape-public-contact-pages",
        action="store_true",
        help=(
            "Follow public creator-supplied links (such as Linktree and a personal site) "
            "to find publicly displayed business emails. Also checks the About-page links."
        ),
    )
    parser.add_argument(
        "--contact-pages-per-channel",
        type=int,
        default=3,
        help="Maximum public contact pages to inspect for each channel. Default: 3.",
    )
    parser.add_argument("--limit", type=int, default=200, help="Maximum channels to save.")
    parser.add_argument("--min-subs", type=int, default=0, help="Minimum subscriber count.")
    parser.add_argument("--max-subs", type=int, default=0, help="Maximum subscriber count. 0 means no max.")
    parser.add_argument(
        "--require-email",
        action="store_true",
        help="Keep only channels with a publicly found email address.",
    )
    parser.add_argument(
        "--exclude-hidden-subs",
        action="store_true",
        help="Exclude channels whose subscriber count is hidden/unavailable.",
    )
    parser.add_argument("--out-csv", default="youtube_influencer_candidates.csv")
    parser.add_argument("--out-json", default="youtube_influencer_candidates.json")
    parser.add_argument(
        "--raw-text",
        action="store_true",
        help="Keep original Unicode text. By default text is cleaned for Excel CSV display.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    api_key = load_api_key(args.api_key)
    keywords = args.keywords or DEFAULT_KEYWORDS

    channel_discovery: dict[str, str] = {}
    for source_type, query in build_discovery_queries(args.mode, keywords):
        label = query or f"topic:{args.topic_id}"
        print(f"[search:youtube] {source_type}: {label}")
        for channel_id, discovery_query in search_channel_ids(
            api_key=api_key,
            query=query,
            pages=args.pages,
            topic_id=args.topic_id,
            region=args.region,
            language=args.language,
            pause_seconds=args.pause,
        ):
            channel_discovery.setdefault(channel_id, discovery_query)
            if len(channel_discovery) >= args.limit * 2:
                break

        if len(channel_discovery) >= args.limit * 2:
            break

    print(f"[enrich:youtube] unique_channel_ids={len(channel_discovery)}")

    candidates: list[YouTubeCandidate] = []
    for item in fetch_channels(api_key, list(channel_discovery), args.pause):
        candidate = channel_to_candidate(
            item,
            channel_discovery.get(item.get("id", ""), ""),
            clean_output_text=not args.raw_text,
        )

        if args.scrape_about_links or args.scrape_public_contact_pages:
            candidate.about_links = scrape_about_links(
                handle_url=candidate.handle_url,
                channel_url=candidate.channel_url,
                pause_seconds=args.pause,
            )
            candidate.contact_urls = merge_url_fields(candidate.contact_urls, candidate.about_links)

        if args.scrape_public_contact_pages:
            page_emails, page_links, checked_pages = scrape_public_contact_pages(
                initial_urls=candidate.contact_urls,
                max_pages=max(1, args.contact_pages_per_channel),
                pause_seconds=args.pause,
            )
            candidate.contact_page_links = page_links
            candidate.contact_pages_checked = checked_pages
            candidate.emails = join_unique_values(candidate.emails, page_emails)
            candidate.email = first_value(candidate.emails)
            if page_emails:
                candidate.email_source = (
                    "description + public_contact_page"
                    if candidate.email_source
                    else "public_contact_page"
                )

        candidate.contact_status = contact_status(candidate.emails, candidate.contact_urls)
        candidate.fit_score = score_channel(
            candidate.title,
            candidate.description,
            candidate.keywords,
            candidate.email,
            int_or_none(candidate.subscriber_count),
        )

        if args.require_email and not candidate.emails:
            continue

        if not passes_filters(
            candidate,
            min_subs=args.min_subs,
            max_subs=args.max_subs,
            include_hidden_subs=not args.exclude_hidden_subs,
        ):
            continue

        candidates.append(candidate)
        if len(candidates) >= args.limit:
            break

    candidates.sort(key=lambda row: row.fit_score, reverse=True)
    save_csv(args.out_csv, candidates)
    save_json(args.out_json, candidates)
    print(f"[done] saved {len(candidates)} candidates to {args.out_csv} and {args.out_json}")


if __name__ == "__main__":
    main()
