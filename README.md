# Health Influencer Outreach MVP

This is a small-sample workflow for finding health creators, collecting public contact paths, and preparing a human-reviewed outreach list. It is designed so that the source can change later without changing the rest of the workflow.

## Current Flow

1. Discover a small creator sample from YouTube or an approved TikTok/Instagram data source.
2. Enrich only public contact information from bios, About links, Linktree-style pages, and creator websites.
3. Create a review queue. A person confirms creator fit and contact details before outreach.
4. Use AI to prepare fit notes and personalized email drafts, then approve the creator and contact route manually.
5. Send a small, approved email batch with an audit log.

## Small Sample: YouTube

```bash
cd outputs
python3 youtube_influencer_mvp.py --mode keyword --keyword "gut health" --pages 1 --min-subs 10000 --limit 20 --scrape-public-contact-pages --contact-pages-per-channel 3
python3 outreach_queue_builder.py --input youtube_influencer_candidates.csv --out outreach_queue_youtube.csv --limit 10
```

Add `--require-email` to the first command when the queue should contain only candidates with a publicly found email. A zero-row result means the channels did not expose an email through public pages; it is not a script failure.

## Small Sample: TikTok / Instagram

The short-video step begins from a CSV exported from an approved creator marketplace or licensed data provider. Fill a copy of `outputs/short_video_input_template.csv`, then run:

```bash
cd outputs
python3 short_video_influencer_mvp.py --input creators.csv --platform tiktok --min-followers 10000 --limit 20 --scrape-public-contact-pages
python3 outreach_queue_builder.py --input short_video_influencer_candidates.csv --out outreach_queue_tiktok.csv --limit 10
```

### Automatic TikTok Discovery

For automatic TikTok discovery, use a Modash Discovery API key in `outputs/.env`:

```bash
MODASH_API_KEY=your_modash_key
```

Then the complete discovery and public-contact workflow is one command:

```bash
cd outputs
python3 tiktok_influencer_mvp.py --keyword "gut health" --min-followers 10000 --limit 30 --scrape-public-contact-pages
```

This writes `tiktok_influencer_candidates.csv` and JSON with TikTok profile links, followers, engagement fields supplied by Modash, public contact paths, public emails found, and a fit score. Use `--dry-run` to inspect the Modash request without spending API credits. Advanced Modash filters can be supplied with `--filter-json`.

## Recheck Public Contact Paths

When a candidate list already exists, run contact enrichment without searching for creators again:

```bash
cd outputs
python3 contact_enrichment.py --input youtube_influencer_candidates.csv --out youtube_contacts_enriched.csv --limit 10 --contact-pages-per-creator 3
```

The command checks only public creator-supplied links such as websites, Linktree-style pages, and Contact/About pages. Use `--skip-public-pages` for a no-network preview of the existing contact fields.

## Credentials and Data Safety

- Copy `outputs/.env.example` to `outputs/.env` and keep all real keys only in `.env`.
- Do not commit `.env`, contact lists, or debug pages. `.gitignore` already excludes them.
- Do not bypass login, CAPTCHA, or platform email-reveal screens.
- Review every outbound message before sending it, especially for health claims.

## Review-Gated Email Outreach

Build a small outreach queue, then open its CSV and fill `review_status=approved` only for creators that a person has checked. Also fill `campaign_angle` and `personalization_note`; they become part of the message. Rows without a public email stay in the queue as `manual_profile_contact` and are not sent automatically.

```bash
cd outputs
python3 outreach_queue_builder.py --input youtube_influencer_candidates.csv --out outreach_queue.csv --limit 10
python3 outreach_sender.py --input outreach_queue.csv --out outreach_queue_preview.csv --brand-name "Your Brand" --dry-run
```

`outreach_sender.py` is a dry-run unless `--send` is supplied. The preview creates an updated queue and a send log but does not connect to any email service. Once the approved rows, message, postal address, and opt-out email have been reviewed, add SMTP settings to `outputs/.env` and run a deliberately small batch:

```bash
python3 outreach_sender.py --input outreach_queue.csv --out outreach_queue_after_send.csv --brand-name "Your Brand" --max-send 5 --pause 45 --send --yes-send-approved
```

The sender only processes rows with `review_status=approved`, a valid `primary_email`, and an outreach status that has not already been sent or opted out. It never sends TikTok, Instagram, or YouTube DMs automatically; those profiles remain manual contact routes. Keep the physical business address and unsubscribe inbox in the email footer, and record opt-outs in the queue before a later run.

## AI Drafting Before Review

Fill the Gemini and campaign markers in `outputs/.env`, then use the AI writer to prepare a fit assessment, risks, a personalized hook, email subject, and message body for each creator. It uses only the details in the CSV and your campaign brief. It never changes `review_status` and never sends an email.

```bash
cd outputs
python3 ai_outreach_writer.py --input outreach_queue.csv --out outreach_queue_ai.csv --limit 10
python3 ai_outreach_writer.py --input outreach_queue.csv --out outreach_queue_ai.csv --limit 10 --generate
```

The first command is a no-cost preview. The second one calls the Gemini API and adds `ai_*` columns to the new CSV. Review `ai_fit_summary`, `ai_risk_flags`, `ai_subject`, and `ai_email_body`; only then set `review_status=approved`. `outreach_sender.py` uses the reviewed AI subject/body when present and otherwise uses the normal email template.

## Next Integration

The next data-source adapter will be selected after a small Modash or HypeAuditor trial/export is available. The existing `short_video_influencer_mvp.py` accepts their CSV exports now; later it can be connected directly to an API key without changing the review-queue step.

## AI Digital Human Sample

`ai_avatar_mvp/` contains an original fictional presenter, a fictional wellness product visual, a 30-second English product-introduction script, and a video-production brief. It is intentionally limited to general wellness language and requires human review before public use.
