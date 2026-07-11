# LumaRoot Digital Human MVP

This is a fictional product-introduction sample for a wellness brand. The host image is an original AI-generated character, not a real person or a cloned identity.

## Brand and Product

- Brand: LumaRoot
- Product: LumaRoot Daily
- Category: fiber and botanical drink mix
- Positioning: a simple daily wellness ritual for people who want to support everyday digestive wellness as part of a balanced routine

## Assets

- `assets/lumaroot-host.jpg`: source image for an image-to-video digital presenter.
- `assets/lumaroot-product.jpg`: vertical product B-roll visual. Add the brand name as video-editor text rather than altering the package image.
- `product_intro_en.txt`: approximately 30-second English voiceover.
- `video_brief.json`: settings, overlays, and safety notes for a video tool.

## Create the First Video

1. In an AI avatar video tool, create an image-based avatar with `assets/lumaroot-host.jpg`.
2. Use a natural US-English female voice. Do not use a cloned voice or a real person's identity.
3. Paste the narration from `product_intro_en.txt`.
4. Set the canvas to vertical `9:16`, 1080 x 1920, with captions on.
5. Insert `assets/lumaroot-product.jpg` as a 3-5 second B-roll shot after the opening.
6. Add the exact overlays from `video_brief.json`, then export an MP4.

## One-Button Local Tool

`video_button.py` starts a small local control page. It works in two modes:

- Preview mode: the `Prepare Script` button is free and creates a reviewed script locally.
- Generate mode: the `Generate Video` button submits the video to HeyGen and shows its final download link.

Set up once:

```bash
cd ai_avatar_mvp
cp .env.example .env
open -e .env
python3 video_button.py
```

Put your HeyGen API key, avatar ID, and voice ID in `.env`, then open `http://127.0.0.1:8765` in a browser. The API key remains only on your computer; the page never displays or stores it.

For the first automated render, create the photo avatar once in HeyGen's Photo-to-Video flow using `assets/lumaroot-host.jpg`, then use its API avatar ID and a selected API voice ID in `.env`. After that one-time setup, each new product script can be submitted from the local button.

## Cost

HeyGen's web free tier can be used for a few manual sample videos. API automation is paid separately on a pay-as-you-go basis, so use `Prepare Script` freely and click `Generate Video` only after the copy is approved.

## Approval Checklist

- No claims about curing, treating, preventing, or diagnosing disease.
- Do not call the presenter a doctor, dietitian, or medical professional.
- Confirm product ingredients, labels, and all marketing claims before any public use.
- Label the video as AI-generated where required by the destination platform or campaign policy.
