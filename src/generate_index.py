#!/usr/bin/env python3
"""reports_index.json を読み、トップページ（レポート一覧）HTML を生成する。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape


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
    html = template.render(reports=sorted_reports)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding="utf-8")
    print(f"index.html generated: {args.output} ({len(sorted_reports)} reports)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
