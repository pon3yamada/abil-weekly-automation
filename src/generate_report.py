#!/usr/bin/env python3
"""週次レポート用 JSON を読み、Jinja2 で HTML を生成する（フェーズ1の骨格）。"""

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

    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("weekly_report.html.j2")
    html = template.render(report=payload["report"])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
