#!/usr/bin/env python3
"""Local one-button controller for a HeyGen product-introduction video.

Run from this folder:
  export HEYGEN_API_KEY="..."
  export HEYGEN_AVATAR_ID="..."
  export HEYGEN_VOICE_ID="..."
  python3 video_button.py

The API credentials stay in this computer's environment and are never sent to
the browser page, written into a file, or committed to GitHub.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests


ROOT = Path(__file__).resolve().parent
HEYGEN_GENERATE_URL = "https://api.heygen.com/v2/video/generate"
HEYGEN_STATUS_URL = "https://api.heygen.com/v1/video_status.get"


def read_dotenv() -> dict[str, str]:
    values: dict[str, str] = {}
    env_path = ROOT / ".env"
    if not env_path.exists():
        return values
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def settings() -> dict[str, str]:
    dotenv = read_dotenv()
    return {
        "api_key": os.getenv("HEYGEN_API_KEY", "").strip() or dotenv.get("HEYGEN_API_KEY", ""),
        "avatar_id": os.getenv("HEYGEN_AVATAR_ID", "").strip() or dotenv.get("HEYGEN_AVATAR_ID", ""),
        "voice_id": os.getenv("HEYGEN_VOICE_ID", "").strip() or dotenv.get("HEYGEN_VOICE_ID", ""),
    }


def make_script(product_name: str, description: str, call_to_action: str) -> str:
    product_name = product_name.strip() or "LumaRoot Daily"
    description = description.strip() or "a simple fiber and botanical drink mix for an everyday wellness routine"
    call_to_action = call_to_action.strip() or f"Learn more about {product_name} today."
    return (
        f"Meet {product_name}, {description}.\n\n"
        "Just add one scoop to water or a smoothie for a simple ritual that fits into real life.\n\n"
        "It is designed to support everyday wellness as part of a balanced diet and active lifestyle.\n\n"
        "It is not a medicine and is not intended to diagnose, treat, cure, or prevent any disease.\n\n"
        f"{call_to_action}"
    )


def prepare_payload(body: dict[str, object]) -> tuple[dict[str, object], str]:
    values = settings()
    product_name = str(body.get("product_name", "LumaRoot Daily"))
    description = str(body.get("description", ""))
    call_to_action = str(body.get("call_to_action", ""))
    script = str(body.get("script", "")).strip() or make_script(product_name, description, call_to_action)
    payload = {
        "video_inputs": [
            {
                "character": {
                    "type": "avatar",
                    "avatar_id": values["avatar_id"],
                    "avatar_style": "normal",
                },
                "voice": {
                    "type": "text",
                    "input_text": script,
                    "voice_id": values["voice_id"],
                    "speed": 1.0,
                },
            }
        ],
        "dimension": {"width": 720, "height": 1280},
        "caption": True,
        "title": f"{product_name} product introduction",
    }
    return payload, script


class AppHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        print(f"[web] {self.address_string()} - {format % args}")

    def send_json(self, payload: dict[str, object], status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self) -> None:
        page = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LumaRoot Video Control</title>
  <style>
    :root { --ink:#17302a; --muted:#5e6e69; --line:#d7e0dc; --surface:#f7faf8; --sage:#7d9d82; --sun:#efc35a; --alert:#8d3d32; }
    * { box-sizing:border-box; }
    body { margin:0; background:#eef3ef; color:var(--ink); font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
    header { background:#17302a; color:#fff; padding:22px 28px; }
    h1 { margin:0; font-size:22px; font-weight:700; letter-spacing:0; }
    header p { margin:4px 0 0; color:#dce8e1; }
    main { max-width:1040px; margin:0 auto; padding:24px; }
    .notice { border-left:4px solid var(--sun); background:#fff8df; padding:10px 12px; margin-bottom:18px; color:#50400d; }
    .layout { display:grid; grid-template-columns:minmax(0,1.25fr) minmax(280px,.75fr); gap:18px; }
    section { background:#fff; border:1px solid var(--line); padding:18px; }
    h2 { font-size:16px; margin:0 0 14px; }
    label { display:block; font-weight:650; margin:12px 0 5px; }
    input, textarea { width:100%; border:1px solid #b9c9c2; border-radius:4px; padding:9px 10px; color:var(--ink); font:inherit; background:#fff; }
    textarea { min-height:100px; resize:vertical; }
    .actions { display:flex; gap:9px; flex-wrap:wrap; margin-top:16px; }
    button { border:0; border-radius:4px; padding:10px 13px; color:#fff; background:#17302a; font:inherit; font-weight:700; cursor:pointer; }
    button.secondary { background:#6f8379; }
    button:disabled { opacity:.55; cursor:wait; }
    .asset { width:100%; max-height:260px; object-fit:cover; border:1px solid var(--line); border-radius:4px; background:var(--surface); }
    .meta { color:var(--muted); font-size:13px; margin:7px 0 16px; }
    #status { min-height:46px; border:1px solid var(--line); background:var(--surface); padding:10px; white-space:pre-wrap; }
    #status.error { border-color:#d7aaa3; color:var(--alert); background:#fff3f0; }
    #download { display:none; margin-top:12px; color:#0a6652; font-weight:700; }
    code { background:#edf2ef; padding:1px 4px; border-radius:3px; }
    @media (max-width:760px) { main { padding:14px; } .layout { grid-template-columns:1fr; } header { padding:18px; } }
  </style>
</head>
<body>
  <header><h1>LumaRoot Video Control</h1><p>Build a product-introduction video, then send it to HeyGen when the API is configured.</p></header>
  <main>
    <div class="notice" id="config">Checking local setup...</div>
    <div class="layout">
      <section>
        <h2>Video Brief</h2>
        <label for="product">Product Name</label><input id="product" value="LumaRoot Daily">
        <label for="description">Reviewed Product Description</label><textarea id="description">a simple fiber and botanical drink mix for an everyday wellness routine</textarea>
        <label for="cta">Call to Action</label><input id="cta" value="Learn more about LumaRoot Daily today.">
        <label for="script">Spoken Script</label><textarea id="script"></textarea>
        <div class="actions">
          <button class="secondary" id="prepare">Prepare Script</button>
          <button id="generate">Generate Video</button>
        </div>
      </section>
      <section>
        <h2>Assets</h2>
        <img class="asset" src="/assets/lumaroot-host.jpg" alt="Fictional digital presenter">
        <p class="meta">Digital presenter source</p>
        <img class="asset" src="/assets/lumaroot-product.jpg" alt="Fictional product package">
        <p class="meta">Product B-roll source</p>
        <h2>Render Status</h2>
        <div id="status">No video task started.</div>
        <a id="download" target="_blank" rel="noreferrer">Open completed video</a>
      </section>
    </div>
  </main>
  <script>
    const get = (id) => document.getElementById(id);
    const fields = () => ({product_name:get('product').value, description:get('description').value, call_to_action:get('cta').value, script:get('script').value});
    let poller = null;
    function status(message, error=false) { const box=get('status'); box.textContent=message; box.className=error?'error':''; }
    async function api(path, options={}) { const response=await fetch(path, {headers:{'Content-Type':'application/json'}, ...options}); const data=await response.json(); if(!response.ok) throw new Error(data.error || 'Request failed'); return data; }
    async function prepare() { try { const data=await api('/api/prepare',{method:'POST',body:JSON.stringify(fields())}); get('script').value=data.script; status('Script ready. Review it before generating.'); } catch(e) { status(e.message,true); } }
    async function check(videoId) { try { const data=await api('/api/status?video_id='+encodeURIComponent(videoId)); const detail=data.detail || {}; status('Video '+videoId+'\nStatus: '+(detail.status || 'processing')); if(detail.status==='completed' && detail.video_url) { clearInterval(poller); get('download').href=detail.video_url; get('download').style.display='block'; } if(detail.status==='failed') clearInterval(poller); } catch(e) { clearInterval(poller); status(e.message,true); } }
    async function generate() { const button=get('generate'); button.disabled=true; get('download').style.display='none'; try { const data=await api('/api/generate',{method:'POST',body:JSON.stringify(fields())}); get('script').value=data.script; status('Submitted to HeyGen. Video ID: '+data.video_id+'\nChecking render status...'); await check(data.video_id); poller=setInterval(()=>check(data.video_id),10000); } catch(e) { status(e.message,true); } finally { button.disabled=false; } }
    get('prepare').onclick=prepare; get('generate').onclick=generate;
    fetch('/api/health').then(r=>r.json()).then(data=>{ get('config').textContent=data.ready ? 'HeyGen API is configured. Generate Video will submit a real render.' : 'Preview mode: Prepare Script works now. Add HEYGEN_API_KEY, HEYGEN_AVATAR_ID, and HEYGEN_VOICE_ID to enable real video generation.'; });
    prepare();
  </script>
</body>
</html>"""
        encoded = page.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_html()
            return
        if parsed.path == "/api/health":
            values = settings()
            self.send_json({"ready": all(values.values())})
            return
        if parsed.path == "/api/status":
            video_id = parse_qs(parsed.query).get("video_id", [""])[0]
            values = settings()
            if not values["api_key"]:
                self.send_json({"error": "Add HEYGEN_API_KEY before checking a video."}, HTTPStatus.BAD_REQUEST)
                return
            try:
                response = requests.get(
                    HEYGEN_STATUS_URL,
                    params={"video_id": video_id},
                    headers={"X-Api-Key": values["api_key"]},
                    timeout=30,
                )
                response.raise_for_status()
                response_json = response.json()
                data = response_json.get("data", response_json)
                self.send_json({"detail": data})
            except requests.RequestException as exc:
                self.send_json({"error": f"HeyGen status request failed: {exc}"}, HTTPStatus.BAD_GATEWAY)
            return
        if parsed.path.startswith("/assets/"):
            path = (ROOT / parsed.path.removeprefix("/")).resolve()
            if ROOT not in path.parents or not path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            content = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path not in {"/api/prepare", "/api/generate"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            body = self.read_json()
            payload, script = prepare_payload(body)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            self.send_json({"error": f"Invalid form data: {exc}"}, HTTPStatus.BAD_REQUEST)
            return

        if self.path == "/api/prepare":
            self.send_json({"script": script, "payload_preview": payload})
            return

        values = settings()
        missing = [name for name, value in values.items() if not value]
        if missing:
            self.send_json(
                {"error": "Preview is ready. Add these environment variables before real rendering: " + ", ".join(f"HEYGEN_{name.upper()}" for name in missing)},
                HTTPStatus.BAD_REQUEST,
            )
            return

        try:
            response = requests.post(
                HEYGEN_GENERATE_URL,
                headers={"X-Api-Key": values["api_key"], "Content-Type": "application/json"},
                json=payload,
                timeout=45,
            )
            response.raise_for_status()
            response_json = response.json()
            data = response_json.get("data", response_json)
            video_id = data.get("video_id")
            if not video_id:
                raise ValueError(f"HeyGen did not return a video_id: {data}")
            self.send_json({"video_id": video_id, "script": script})
        except (requests.RequestException, ValueError) as exc:
            self.send_json({"error": f"HeyGen generation request failed: {exc}"}, HTTPStatus.BAD_GATEWAY)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local LumaRoot video generation button.")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), AppHandler)
    print(f"[ready] Open http://127.0.0.1:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
