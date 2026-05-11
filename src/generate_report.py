#!/usr/bin/env python3
"""週次レポート用 JSON を読み、Jinja2 で HTML を生成する（フェーズ1の骨格）。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

DEFAULT_PASSWORD_HASH = os.environ.get(
    "REPORT_PASSWORD_HASH",
    "10bd0d13c822595f6995db0dc2c90b9ea38f0ce5e9c90cafa56a671529a6bb08",  # abil-ai
)

FOOTER_DISCLAIMER = (
    "このレポートは自動生成されています。"
    "数値は Shopify および各広告プラットフォームのデータに基づきます。"
)


def _footer_generated_at_jp() -> str:
    d = datetime.now(ZoneInfo("Asia/Tokyo"))
    return f"{d.year}年{d.month}月{d.day}日 {d.hour:02d}:{d.minute:02d}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        required=True,
        help="レポート用 JSON（ルートに report オブジェクト）",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="出力 HTML パス",
    )
    parser.add_argument(
        "--password-hash",
        default=DEFAULT_PASSWORD_HASH,
        help="SHA-256 ハッシュ（デフォルト: 環境変数 REPORT_PASSWORD_HASH）",
    )
    args = parser.parse_args()

    src_dir = Path(__file__).resolve().parent
    template_dir = src_dir / "templates"

    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"error: failed to read JSON: {e}", file=sys.stderr)
        return 1

    if "report" not in payload:
        print("error: JSON root must contain a 'report' object", file=sys.stderr)
        return 1

    report = payload["report"]
    footer = report.setdefault("footer", {})
    footer["disclaimer"] = FOOTER_DISCLAIMER
    footer["generated_at"] = _footer_generated_at_jp()

    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("weekly_report.html.j2")
    html = template.render(report=report, password_hash=args.password_hash)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
