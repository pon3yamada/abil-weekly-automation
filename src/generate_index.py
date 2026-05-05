#!/usr/bin/env python3
"""reports_index.json を読み、トップページ（レポート一覧）HTML を生成する。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

DEFAULT_PASSWORD_HASH = os.environ.get(
    "REPORT_PASSWORD_HASH",
    "10bd0d13c822595f6995db0dc2c90b9ea38f0ce5e9c90cafa56a671529a6bb08",  # abil-ai
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        default=Path(__file__).resolve().parent / "data" / "reports_index.json",
        help="レポート一覧 JSON（デフォルト: src/data/reports_index.json）",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="出力 HTML パス（例: _site/index.html）",
    )
    parser.add_argument(
        "--password-hash",
        default=DEFAULT_PASSWORD_HASH,
        help="SHA-256 ハッシュ（デフォルト: 環境変数 REPORT_PASSWORD_HASH）",
    )
    args = parser.parse_args()

    try:
        reports = json.loads(args.input.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"error: failed to read reports index: {e}", file=sys.stderr)
        return 1

    src_dir = Path(__file__).resolve().parent
    template_dir = src_dir / "templates"

    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("index.html.j2")
    # 新しい順に並べる
    sorted_reports = sorted(reports, key=lambda r: r.get("slug", ""), reverse=True)
    html = template.render(reports=sorted_reports, password_hash=args.password_hash)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding="utf-8")
    print(f"index.html generated: {args.output} ({len(sorted_reports)} reports)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
