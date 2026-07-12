#!/usr/bin/env python3
"""Use the Gemini API to draft review-only creator outreach content.

The script adds AI suggestions to an outreach queue CSV. It never changes
review_status, never discovers private contact information, and never sends an
email. A person must review and approve each row before outreach_sender.py can
deliver it.

Setup in outputs/.env:
  GEMINI_API_KEY=your_api_key

Example:
  python3 ai_outreach_writer.py --input outreach_queue.csv --out outreach_queue_ai.csv \
    --brand-name "LumaRoot" --campaign-brief "Paid wellness creator campaign for a daily fiber blend." \
    --generate --limit 10
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests


GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-2.5-flash"
AI_FIELDS = [
    "ai_fit_score",
    "ai_fit_decision",
    "ai_fit_summary",
    "ai_personalization_note",
    "ai_campaign_angle",
    "ai_subject",
    "ai_email_body",
    "ai_risk_flags",
    "ai_needs_manual_review",
    "ai_model",
    "ai_generated_at",
    "ai_error",
]
SKIP_OUTREACH_STATUSES = {"sent", "opted_out", "unsubscribed", "do_not_contact"}


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


def api_key(argument: str, dotenv: dict[str, str]) -> str:
    key = argument.strip() or setting("GEMINI_API_KEY", dotenv)
    if not key:
        raise ValueError("Missing GEMINI_API_KEY. Add it to outputs/.env or pass --api-key.")
    if key.startswith("PASTE_") or key.startswith("YOUR_"):
        raise ValueError("GEMINI_API_KEY still has the example marker. Replace it with your real key.")
    return key


def required_value(value: str, name: str) -> str:
    value = value.strip()
    if not value or value.startswith("PASTE_") or value.startswith("REPLACE_") or value.startswith("YOUR_"):
        raise ValueError(f"{name} is missing. Replace its marker in outputs/.env or pass it in the command.")
    return value


def queue_context(row: dict[str, str]) -> dict[str, str]:
    """Pass only workflow fields needed to assess fit and write a draft."""
    useful_fields = [
        "creator_name",
        "handle",
        "platform",
        "profile_url",
        "audience_size",
        "fit_score",
        "creator_bio",
        "niche_or_topics",
        "contact_status",
        "campaign_angle",
        "personalization_note",
        "keywords",
        "topic_categories",
    ]
    return {field: row.get(field, "") for field in useful_fields if row.get(field, "")}


def output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "fit_score": {"type": "integer", "minimum": 0, "maximum": 100},
            "fit_decision": {"type": "string", "enum": ["good_fit", "needs_review", "poor_fit"]},
            "fit_summary": {"type": "string"},
            "personalization_note": {"type": "string"},
            "campaign_angle": {"type": "string"},
            "email_subject": {"type": "string"},
            "email_body": {"type": "string"},
            "risk_flags": {"type": "array", "items": {"type": "string"}},
            "needs_manual_review": {"type": "boolean"},
        },
        "required": [
            "fit_score",
            "fit_decision",
            "fit_summary",
            "personalization_note",
            "campaign_angle",
            "email_subject",
            "email_body",
            "risk_flags",
            "needs_manual_review",
        ],
        "additionalProperties": False,
    }


INSTRUCTIONS = """You write careful, concise creator-partnership outreach drafts for a wellness brand.
Use only facts supplied in the creator record and campaign brief. Never invent a video, credential,
performance result, audience trait, email address, or relationship. Do not make medical, disease,
diagnostic, treatment, cure, or guaranteed-result claims. If the material raises health-claim,
credential, brand-safety, or poor-fit concerns, include them in risk_flags and set
needs_manual_review to true. Be respectful and non-manipulative.

Return a plain-text email_body of 70-120 words in the requested language. Include a friendly
greeting and a clear paid-collaboration invitation. Do not include a signature, postal address,
unsubscribe line, price promise, links, or unsupported factual claims: the sending system adds
the compliance footer after human approval. A good personalization_note is one specific sentence
grounded in the supplied record. The output is a draft only, not approval to contact anyone."""


def text_from_response(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates", [])
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content", {})
        if not isinstance(content, dict):
            continue
        text = "".join(
            part.get("text", "")
            for part in content.get("parts", [])
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
        if text.strip():
            return text
    prompt_feedback = payload.get("promptFeedback", {})
    if isinstance(prompt_feedback, dict) and prompt_feedback.get("blockReason"):
        raise ValueError(f"Gemini blocked the prompt: {prompt_feedback['blockReason']}")
    raise ValueError("Gemini response did not contain text output.")


def generate_draft(
    key: str,
    model: str,
    brand_name: str,
    campaign_brief: str,
    language: str,
    row: dict[str, str],
) -> dict[str, Any]:
    prompt = {
        "brand_name": brand_name,
        "campaign_brief": campaign_brief,
        "requested_language": language,
        "creator_record": queue_context(row),
    }
    request = {
        "systemInstruction": {"parts": [{"text": INSTRUCTIONS}]},
        "contents": [{"role": "user", "parts": [{"text": json.dumps(prompt, ensure_ascii=False)}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": output_schema(),
            "maxOutputTokens": 700,
        },
    }
    response = requests.post(
        GEMINI_URL.format(model=model),
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        json=request,
        timeout=90,
    )
    if not response.ok:
        message = response.text[:1000]
        raise RuntimeError(f"Gemini returned {response.status_code}: {message}")
    try:
        draft = json.loads(text_from_response(response.json()))
    except (json.JSONDecodeError, ValueError) as error:
        raise RuntimeError(f"Could not parse the structured model response: {error}") from error
    if not isinstance(draft, dict):
        raise RuntimeError("The model response was not a JSON object.")
    return draft


def apply_draft(row: dict[str, str], draft: dict[str, Any], model: str) -> None:
    row["ai_fit_score"] = str(draft.get("fit_score", ""))
    row["ai_fit_decision"] = str(draft.get("fit_decision", ""))
    row["ai_fit_summary"] = str(draft.get("fit_summary", ""))
    row["ai_personalization_note"] = str(draft.get("personalization_note", ""))
    row["ai_campaign_angle"] = str(draft.get("campaign_angle", ""))
    row["ai_subject"] = str(draft.get("email_subject", ""))
    row["ai_email_body"] = str(draft.get("email_body", ""))
    flags = draft.get("risk_flags", [])
    row["ai_risk_flags"] = " | ".join(str(flag) for flag in flags) if isinstance(flags, list) else str(flags)
    row["ai_needs_manual_review"] = str(bool(draft.get("needs_manual_review", True))).lower()
    row["ai_model"] = model
    row["ai_generated_at"] = utc_now()
    row["ai_error"] = ""


def write_csv(path: str, fields: list[str], rows: list[dict[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate review-only AI creator-fit and email drafts.")
    parser.add_argument("--input", required=True, help="Outreach queue or creator candidate CSV.")
    parser.add_argument("--out", default="outreach_queue_ai.csv", help="CSV containing AI suggestions.")
    parser.add_argument("--brand-name", default="", help="Brand name. Defaults to AI_BRAND_NAME in outputs/.env.")
    parser.add_argument("--campaign-brief", default="", help="Campaign brief. Defaults to AI_CAMPAIGN_BRIEF in outputs/.env.")
    parser.add_argument("--language", default="", help="Draft language. Defaults to AI_DRAFT_LANGUAGE in outputs/.env.")
    parser.add_argument("--model", default="", help=f"Gemini model. Defaults to GEMINI_MODEL or {DEFAULT_MODEL}.")
    parser.add_argument("--api-key", default="", help="Prefer GEMINI_API_KEY in outputs/.env.")
    parser.add_argument("--limit", type=int, default=20, help="Maximum eligible creators to process.")
    parser.add_argument("--pause", type=float, default=0.5, help="Seconds between API calls.")
    parser.add_argument("--only-approved", action="store_true", help="Only draft for rows already marked review_status=approved.")
    parser.add_argument("--generate", action="store_true", help="Call the API. Without it, show a safe preview only.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.limit < 1:
        raise SystemExit("--limit must be at least 1.")
    if args.pause < 0:
        raise SystemExit("--pause cannot be negative.")

    with open(args.input, newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        fields = list(reader.fieldnames or [])
        if not fields:
            raise SystemExit("Input CSV has no header row.")
        rows = [{(key or "").strip(): (value or "").strip() for key, value in raw.items()} for raw in reader]

    eligible: list[dict[str, str]] = []
    for row in rows:
        status = row.get("outreach_status", "").strip().lower()
        review = row.get("review_status", "").strip().lower()
        if status in SKIP_OUTREACH_STATUSES or (args.only_approved and review != "approved"):
            continue
        eligible.append(row)
        if len(eligible) >= args.limit:
            break

    if not args.generate:
        print(f"[preview] would generate drafts for {len(eligible)} creator rows; no API call was made.")
        for row in eligible[:5]:
            print(f"[preview] {row.get('creator_name') or row.get('handle') or row.get('candidate_id', 'unknown creator')}")
        print("[next] add --generate after confirming the campaign brief and API key.")
        return

    dotenv = read_dotenv()
    try:
        key = api_key(args.api_key, dotenv)
        brand_name = required_value(args.brand_name or setting("AI_BRAND_NAME", dotenv), "AI_BRAND_NAME / --brand-name")
        campaign_brief = required_value(
            args.campaign_brief or setting("AI_CAMPAIGN_BRIEF", dotenv),
            "AI_CAMPAIGN_BRIEF / --campaign-brief",
        )
        language = args.language.strip() or setting("AI_DRAFT_LANGUAGE", dotenv, "English")
        model = args.model.strip() or setting("GEMINI_MODEL", dotenv, DEFAULT_MODEL)
    except ValueError as error:
        raise SystemExit(f"[configuration-error] {error}") from error

    completed = 0
    failed = 0
    for row in eligible:
        name = row.get("creator_name") or row.get("handle") or row.get("candidate_id", "unknown creator")
        try:
            draft = generate_draft(key, model, brand_name, campaign_brief, language, row)
            apply_draft(row, draft, model)
            completed += 1
            print(f"[drafted] {name}")
        except (requests.RequestException, RuntimeError, ValueError) as error:
            row["ai_error"] = str(error)
            row["ai_generated_at"] = utc_now()
            row["ai_model"] = model
            failed += 1
            print(f"[failed] {name}: {error}")
        if completed + failed < len(eligible) and args.pause:
            time.sleep(args.pause)

    output_fields = fields + [field for field in AI_FIELDS if field not in fields]
    write_csv(args.out, output_fields, rows)
    print(f"[done] drafted={completed} failed={failed} saved={args.out}")


if __name__ == "__main__":
    main()
