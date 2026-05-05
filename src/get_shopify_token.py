#!/usr/bin/env python3
"""
Shopify Partners アプリの OAuth フローでアクセストークンを1回取得し .env に保存する。

事前準備:
  1. Partners ダッシュボード → 設定 → 資格情報 → リダイレクト URL に
     http://localhost:3000/callback を追加して保存
  2. .env に SHOPIFY_CLIENT_ID と SHOPIFY_CLIENT_SECRET を記入

実行:
  python src/get_shopify_token.py
"""

from __future__ import annotations

import http.server
import os
import secrets
import threading
import urllib.parse
import webbrowser
from pathlib import Path

import requests
from dotenv import load_dotenv, set_key

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"

load_dotenv(ENV_FILE)

SHOP = os.environ.get("SHOPIFY_STORE", "").strip().lower()
SHOP = SHOP.removeprefix("https://").removeprefix("http://").rstrip("/")
CLIENT_ID = os.environ.get("SHOPIFY_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("SHOPIFY_CLIENT_SECRET", "").strip()
REDIRECT_URI = "http://localhost:3000/callback"
SCOPES = "read_all_orders,read_analytics,read_customers,read_orders"

_result: dict = {}
_nonce = secrets.token_hex(16)


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        state = params.get("state", [None])[0]
        if state != _nonce:
            self._respond(400, b"<h1>Error: state mismatch</h1>")
            return

        code = params.get("code", [None])[0]
        if not code:
            self._respond(400, b"<h1>Error: code not found</h1>")
            return

        try:
            r = requests.post(
                f"https://{SHOP}/admin/oauth/access_token",
                json={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "code": code},
                timeout=30,
            )
            r.raise_for_status()
            _result["token"] = r.json()["access_token"]
            self._respond(200, b"<h1>Success! \xe3\x82\xbf\xe3\x83\x96\xe3\x82\x92\xe9\x96\x89\xe3\x81\x98\xe3\x81\xa6\xe3\x81\x8f\xe3\x81\xa0\xe3\x81\x95\xe3\x81\x84</h1>")
        except Exception as exc:
            _result["error"] = str(exc)
            self._respond(500, f"<h1>Error: {exc}</h1>".encode())

        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def _respond(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_) -> None:  # suppress request logs
        pass


def main() -> int:
    if not SHOP:
        print("error: .env に SHOPIFY_STORE が未設定です")
        return 1
    if not CLIENT_ID:
        print("error: .env に SHOPIFY_CLIENT_ID が未設定です")
        return 1
    if not CLIENT_SECRET:
        print("error: .env に SHOPIFY_CLIENT_SECRET が未設定です")
        return 1

    auth_url = (
        f"https://{SHOP}/admin/oauth/authorize"
        f"?client_id={CLIENT_ID}"
        f"&scope={SCOPES}"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI, safe='')}"
        f"&state={_nonce}"
    )

    print(f"ブラウザで認証ページを開きます...\n{auth_url}\n")
    webbrowser.open(auth_url)
    print("ポート 3000 でコールバック待機中... （ブラウザで「インストール」を承認してください）")

    server = http.server.HTTPServer(("localhost", 3000), _CallbackHandler)
    server.serve_forever()

    if "error" in _result:
        print(f"\nerror: {_result['error']}")
        return 1

    token = _result["token"]
    print(f"\nアクセストークン取得成功: {token[:12]}...")

    if not ENV_FILE.exists():
        ENV_FILE.write_text("", encoding="utf-8")

    set_key(str(ENV_FILE), "SHOPIFY_ACCESS_TOKEN", token)
    print(f".env の SHOPIFY_ACCESS_TOKEN を更新しました: {ENV_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
