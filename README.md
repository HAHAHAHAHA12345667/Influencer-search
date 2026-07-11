# Health Influencer Outreach MVP

This is a small-sample workflow for finding health creators, collecting public contact paths, and preparing a human-reviewed outreach list. It is designed so that the source can change later without changing the rest of the workflow.

## Current Flow

1. Discover a small creator sample from YouTube or an approved TikTok/Instagram data source.
2. Enrich only public contact information from bios, About links, Linktree-style pages, and creator websites.
3. Create a review queue. A person confirms creator fit and contact details before outreach.
4. Send approved outreach manually or through a future consent-aware email tool.

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

## Credentials and Data Safety

- Copy `outputs/.env.example` to `outputs/.env` and keep all real keys only in `.env`.
- Do not commit `.env`, contact lists, or debug pages. `.gitignore` already excludes them.
- Do not bypass login, CAPTCHA, or platform email-reveal screens.
- Review every outbound message before sending it, especially for health claims.

## Next Integration

The next data-source adapter will be selected after a small Modash or HypeAuditor trial/export is available. The existing `short_video_influencer_mvp.py` accepts their CSV exports now; later it can be connected directly to an API key without changing the review-queue step.

## AI Digital Human Sample

`ai_avatar_mvp/` contains an original fictional presenter, a fictional wellness product visual, a 30-second English product-introduction script, and a video-production brief. It is intentionally limited to general wellness language and requires human review before public use.
