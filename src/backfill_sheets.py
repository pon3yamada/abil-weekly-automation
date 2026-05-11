#!/usr/bin/env python3
"""過去週のレポートJSONを生成し、Google Sheetsへまとめて反映する。"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable or "python3"


def _last_closed_week_monday(anchor: date) -> date:
    mon_this = anchor - timedelta(days=anchor.weekday())
    return mon_this - timedelta(days=7)


def _run(cmd: list[str], *, dry_run: bool, continue_on_error: bool) -> bool:
    printable = " ".join(cmd)
    print(f"$ {printable}", file=sys.stderr)
    if dry_run:
        return True
    result = subprocess.run(cmd, cwd=ROOT, check=False)
    if result.returncode == 0:
        return True
    if continue_on_error:
        print(f"warning: 失敗しましたが継続します（exit={result.returncode}）: {printable}", file=sys.stderr)
        return False
    raise subprocess.CalledProcessError(result.returncode, cmd)


def _week_starts(*, anchor: date, weeks: int, start_date: str, end_date: str) -> list[date]:
    if start_date or end_date:
        if start_date and not end_date:
            start = date.fromisoformat(start_date)
            end = _last_closed_week_monday(anchor)
        elif end_date and start_date:
            start = date.fromisoformat(start_date)
            end = date.fromisoformat(end_date)
        else:
            raise ValueError("--start-date のみ指定するか、--start-date と --end-date の両方を指定してください")

        if start.weekday() != 0:
            raise ValueError("--start-date は月曜日を指定してください")
        if end.weekday() != 0:
            raise ValueError("--end-date が指定されているときは月曜日にしてください（省略時は直近締め週の月曜に自動決定されます）")

        if end < start:
            raise ValueError("--end-date は --start-date 以降を指定してください")
        out: list[date] = []
        cur = start
        while cur <= end:
            out.append(cur)
            cur += timedelta(days=7)
        return out

    if weeks <= 0:
        raise ValueError("--weeks は1以上を指定してください")
    last_mon = _last_closed_week_monday(anchor)
    return [last_mon - timedelta(days=7 * i) for i in reversed(range(weeks))]


def main() -> int:
    load_dotenv(ROOT / ".env")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weeks", type=int, default=52, help="直近締め週から何週分を投入するか")
    parser.add_argument("--start-date", default="", help="投入開始週の月曜日 YYYY-MM-DD")
    parser.add_argument("--end-date", default="", help="投入終了週の月曜日。省略時は直近締め週の月曜")
    parser.add_argument("--anchor-date", default="", help="直近締め週計算の基準日 YYYY-MM-DD")
    parser.add_argument("--base-template", type=Path, default=ROOT / "src" / "data" / "sample_report.json")
    parser.add_argument("--work-dir", type=Path, default=ROOT / "build" / "backfill")
    parser.add_argument("--sleep-seconds", type=float, default=1.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--skip-ads", action="store_true", help="広告API取得をスキップしてShopifyのみ反映")
    parser.add_argument("--skip-sheets", action="store_true", help="Sheets書き込みをスキップ")
    parser.add_argument("--spreadsheet-id", default="", help="書き込み先Spreadsheet ID（未指定なら.envの値）")
    parser.add_argument("--sheet-name", default="", help="書き込み先シート名（未指定なら.envまたは既定値）")
    parser.add_argument("--include-test", action="store_true", help="Shopifyのテスト注文を含める")
    parser.add_argument("--paid-only", action="store_true", help="Shopifyのpaid注文のみ集計")
    args = parser.parse_args()

    anchor = date.fromisoformat(args.anchor_date) if args.anchor_date else datetime.now().date()
    week_starts = _week_starts(
        anchor=anchor,
        weeks=args.weeks,
        start_date=args.start_date,
        end_date=args.end_date,
    )

    args.work_dir.mkdir(parents=True, exist_ok=True)
    print(f"Backfill weeks: {len(week_starts)}", file=sys.stderr)

    ok_count = 0
    fail_count = 0

    for week_mon in week_starts:
        week_sun = week_mon + timedelta(days=6)
        # fetch_shopify.py は「基準日の属する週のひとつ前の週」を対象にする。
        shopify_anchor = week_mon + timedelta(days=7)
        out_json = args.work_dir / f"report_{week_mon.isoformat()}_{week_sun.isoformat()}.json"

        print(f"\n=== {week_mon.isoformat()} 〜 {week_sun.isoformat()} ===", file=sys.stderr)
        succeeded = True

        shopify_cmd = [
            PYTHON,
            "src/fetch_shopify.py",
            "--anchor-date",
            shopify_anchor.isoformat(),
            "--merge-into",
            str(args.base_template),
            "-o",
            str(out_json),
        ]
        if args.include_test:
            shopify_cmd.append("--include-test")
        if args.paid_only:
            shopify_cmd.append("--paid-only")
        succeeded = _run(shopify_cmd, dry_run=args.dry_run, continue_on_error=args.continue_on_error) and succeeded

        if not args.skip_ads:
            meta_cmd = [
                PYTHON,
                "src/fetch_meta.py",
                "--since",
                week_mon.isoformat(),
                "--until",
                week_sun.isoformat(),
                "--base",
                str(out_json),
                "--out",
                str(out_json),
            ]
            succeeded = _run(meta_cmd, dry_run=args.dry_run, continue_on_error=args.continue_on_error) and succeeded

            google_cmd = [
                PYTHON,
                "src/fetch_google_ads.py",
                "--since",
                week_mon.isoformat(),
                "--until",
                week_sun.isoformat(),
                "--base",
                str(out_json),
                "--out",
                str(out_json),
            ]
            succeeded = _run(google_cmd, dry_run=args.dry_run, continue_on_error=args.continue_on_error) and succeeded

        if not args.skip_sheets:
            sheets_cmd = [
                PYTHON,
                "src/append_to_sheets.py",
                "--base",
                str(out_json),
            ]
            if args.spreadsheet_id:
                sheets_cmd.extend(["--spreadsheet-id", args.spreadsheet_id])
            if args.sheet_name:
                sheets_cmd.extend(["--sheet-name", args.sheet_name])
            succeeded = _run(sheets_cmd, dry_run=args.dry_run, continue_on_error=args.continue_on_error) and succeeded

        if succeeded:
            ok_count += 1
        else:
            fail_count += 1

        if args.sleep_seconds > 0 and week_mon != week_starts[-1] and not args.dry_run:
            time.sleep(args.sleep_seconds)

    print(f"\n完了: success={ok_count}, failed={fail_count}", file=sys.stderr)
    return 0 if fail_count == 0 or args.continue_on_error else 1


if __name__ == "__main__":
    raise SystemExit(main())
