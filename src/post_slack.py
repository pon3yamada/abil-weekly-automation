#!/usr/bin/env python3
"""週次レポート公開を Slack Incoming Webhook に投稿する。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from dotenv import load_dotenv


def _one_line_summary(report: dict[str, Any]) -> str:
    summ = report.get("summary") or {}
    parts: list[str] = []
    sales = summ.get("sales") or {}
    if sales.get("value"):
        v = sales["value"]
        d = sales.get("delta") or ""
        parts.append(f"売上 {v}" + (f"（{d}）" if d else ""))
    mer = summ.get("mer") or {}
    if mer.get("value"):
        parts.append(f"MER {mer['value']}")
    ads = summ.get("ad_spend") or {}
    if ads.get("value"):
        parts.append(f"広告費 {ads['value']}")
    return " / ".join(parts) if parts else "（サマリーなし）"


def build_blocks(*, period: str, overall: str, score_sub: str, summary_line: str, report_url: str) -> list[dict[str, Any]]:
    link_md = f"<{report_url}|週次レポートを開く>"
    subtitle = score_sub.strip() if isinstance(score_sub, str) else ""

    texts: list[str] = [
        f"*期間:* {period}",
        f"*総合評価:* {overall}",
    ]
    if subtitle:
        texts.append(f"_{subtitle}_")
    texts.append(f"*ハイライト:* {summary_line}")
    texts.append(link_md)

    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "週次レポートを公開しました", "emoji": True},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(texts)},
        },
    ]


def post_webhook(webhook_url: str, payload: dict[str, Any], timeout: float = 15.0) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        webhook_url,
        data=body,
        headers={"content-type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urlopen(req, timeout=timeout) as resp:
        if resp.status not in (200, 201):
            raise RuntimeError(f"Slack webhook HTTP {resp.status}")


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        type=Path,
        help="レポート JSON（--period 等と併用可）",
    )
    parser.add_argument("--period", help="期間文字列（JSON より優先）")
    parser.add_argument("--overall-score", help="総合スコア（JSON より優先）")
    parser.add_argument("--score-subtitle", default="", help="サブタイトル")
    parser.add_argument("--summary-line", help="1行サマリー（未指定時は JSON から生成）")
    parser.add_argument(
        "--report-url",
        required=True,
        help="公開レポートの URL（末尾スラッシュ可）",
    )
    parser.add_argument(
        "--webhook-url",
        help="Slack Webhook URL（未指定時は環境変数 SLACK_WEBHOOK_URL）",
    )
    args = parser.parse_args()

    webhook = (args.webhook_url or os.environ.get("SLACK_WEBHOOK_URL") or "").strip()
    if not webhook:
        print("notice: SLACK_WEBHOOK_URL unset; skip Slack post", file=sys.stderr)
        return 0

    period = (args.period or "").strip()
    overall = (args.overall_score or "").strip()
    score_sub = args.score_subtitle or ""
    summary_line = (args.summary_line or "").strip()

    if args.base:
        try:
            data = json.loads(args.base.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"error: failed to read JSON: {e}", file=sys.stderr)
            return 1
        report = data.get("report")
        if not isinstance(report, dict):
            print("error: JSON root must contain 'report' object", file=sys.stderr)
            return 1
        if not period:
            period = str(report.get("period_range") or "").strip()
        if not overall:
            overall = str(report.get("overall_score") or "—").strip()
        if not score_sub:
            score_sub = str(report.get("score_subtitle") or "")
        if not summary_line:
            summary_line = _one_line_summary(report)

    if not period:
        print("error: period is required (or pass --base with period_range)", file=sys.stderr)
        return 1
    if not overall:
        overall = "—"
    if not summary_line:
        summary_line = "（サマリーなし）"

    report_url = args.report_url.rstrip("/") + "/"

    payload = {
        "text": f"週次レポート: {period}\n{report_url}",
        "blocks": build_blocks(
            period=period,
            overall=overall,
            score_sub=score_sub,
            summary_line=summary_line,
            report_url=report_url,
        ),
    }

    try:
        post_webhook(webhook, payload)
    except Exception as e:
        print(f"error: Slack post failed: {e}", file=sys.stderr)
        return 1

    print("Slack notification sent.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
