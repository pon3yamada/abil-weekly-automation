#!/usr/bin/env python3
"""過去週の Meta・Google・サマリーデータを正しい日付で再取得し、Sheets を上書きする。

タイムゾーンずれで誤ったデータが書き込まれた週を対象に、
fetch_shopify / fetch_meta / fetch_google_ads を正しい期間で実行して
append_to_sheets.HEADER の全列を上書きします。

使い方:
    python3 src/patch_sheet_ads.py \\
        --start-date 2026-05-18 \\
        --end-date   2026-06-07 \\
        --dry-run
    # 確認後に --dry-run を外して本実行
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import gspread
from dotenv import load_dotenv

import append_to_sheets

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable or "python3"
SRC = ROOT / "src"


def _week_monday_range(start_mon: date, end_mon: date) -> list[date]:
    if start_mon.weekday() != 0 or end_mon.weekday() != 0:
        raise ValueError("--start-date / --end-date はどちらも月曜 (weekday=0) である必要があります")
    if end_mon < start_mon:
        raise ValueError("--end-date は --start-date 以降の月曜を指定してください")
    out: list[date] = []
    cur = start_mon
    while cur <= end_mon:
        out.append(cur)
        cur += timedelta(days=7)
    return out


def _period_sheet_value(period_range: str) -> str:
    return (period_range or "").replace("〜 ", "\n〜 ")


def _find_col_for_period(period_row: list[str], period_key: str) -> int | None:
    """2行目リストから期間が一致する列番号を 1始まりで返す。なければ None。"""
    variants = {
        period_key,
        period_key.replace("\n", ""),
        " ".join(period_key.replace("\n", " ").split()),
    }
    for j0, cell in enumerate(period_row):
        if j0 == 0:
            continue
        if cell in variants:
            return j0 + 1
    return None


def run_pipeline(week_mon: date, work_dir: Path, base_template: Path, *, dry_run: bool) -> dict | None:
    """1週分のパイプライン（Shopify→Meta→Google）を実行し、report dict を返す。"""
    week_sun = week_mon + timedelta(days=6)
    shopify_anchor = (week_mon + timedelta(days=7)).isoformat()
    since = week_mon.isoformat()
    until = week_sun.isoformat()
    out_json = work_dir / f"report_{since}_{until}.json"

    label = f"{since} 〜 {until}"
    print(f"\n=== {label} ===", file=sys.stderr)

    if dry_run:
        print(f"[dry-run] anchor={shopify_anchor} since={since} until={until}", file=sys.stderr)
        return None

    # ── Shopify
    cmd_shopify = [
        PYTHON, str(SRC / "fetch_shopify.py"),
        "--anchor-date", shopify_anchor,
        "--merge-into", str(base_template),
        "-o", str(out_json),
    ]
    r = subprocess.run(cmd_shopify, cwd=ROOT, check=False, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[Shopify] FAILED exit={r.returncode}\n{r.stderr}", file=sys.stderr)
        return None
    print(f"[Shopify] OK", file=sys.stderr)

    # ── Meta
    cmd_meta = [
        PYTHON, str(SRC / "fetch_meta.py"),
        "--since", since, "--until", until,
        "--base", str(out_json), "--out", str(out_json),
    ]
    r = subprocess.run(cmd_meta, cwd=ROOT, check=False, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[Meta] FAILED exit={r.returncode}\n{r.stderr}", file=sys.stderr)
    else:
        print(f"[Meta] OK", file=sys.stderr)

    # ── Google
    cmd_google = [
        PYTHON, str(SRC / "fetch_google_ads.py"),
        "--since", since, "--until", until,
        "--base", str(out_json), "--out", str(out_json),
    ]
    r = subprocess.run(cmd_google, cwd=ROOT, check=False, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[Google] FAILED exit={r.returncode}\n{r.stderr}", file=sys.stderr)
    else:
        print(f"[Google] OK", file=sys.stderr)

    doc = json.loads(out_json.read_text(encoding="utf-8"))
    return doc.get("report", {})


def main() -> int:
    load_dotenv(ROOT / ".env")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", required=True, help="修正開始週の月曜 YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="修正終了週の月曜 YYYY-MM-DD")
    parser.add_argument(
        "--spreadsheet-id",
        default=os.environ.get("GOOGLE_SHEETS_SPREADSHEET_ID", ""),
    )
    parser.add_argument(
        "--sheet-name",
        default=os.environ.get("GOOGLE_SHEETS_SHEET_NAME", "週次データ"),
    )
    parser.add_argument(
        "--base-template",
        type=Path,
        default=ROOT / "src" / "data" / "sample_report.json",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=ROOT / "build" / "patch_ads",
    )
    parser.add_argument("--sleep-seconds", type=float, default=1.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    args = parser.parse_args()

    if not args.spreadsheet_id:
        print("error: --spreadsheet-id または GOOGLE_SHEETS_SPREADSHEET_ID を指定してください", file=sys.stderr)
        return 1

    start_mon = date.fromisoformat(args.start_date)
    end_mon = date.fromisoformat(args.end_date)
    week_mons = _week_monday_range(start_mon, end_mon)

    args.work_dir.mkdir(parents=True, exist_ok=True)

    # Sheets 接続（dry-run でも接続チェックは省略）
    ws = None
    all_vals: list[list[str]] = []
    if not args.dry_run:
        try:
            creds = append_to_sheets._get_credentials()
        except Exception as e:
            print(f"error: 認証: {e}", file=sys.stderr)
            return 1
        gc = gspread.authorize(creds)
        try:
            spreadsheet = gc.open_by_key(args.spreadsheet_id)
        except gspread.exceptions.SpreadsheetNotFound:
            print(f"error: スプレッドシート '{args.spreadsheet_id}' が見つかりません", file=sys.stderr)
            return 1
        try:
            ws = spreadsheet.worksheet(args.sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            print(f"error: シート '{args.sheet_name}' が見つかりません", file=sys.stderr)
            return 1
        all_vals = ws.get_all_values()
        print(f"info: シート取得完了 {len(all_vals)} 行 × {max(len(r) for r in all_vals) if all_vals else 0} 列", file=sys.stderr)

    ok, fail = 0, 0

    for week_mon in week_mons:
        report = run_pipeline(week_mon, args.work_dir, args.base_template, dry_run=args.dry_run)

        if args.dry_run:
            ok += 1
            continue

        if report is None:
            fail += 1
            if not args.continue_on_error:
                return 1
            continue

        # 期間キーを Sheets 形式に変換
        period_key = _period_sheet_value(report.get("period_range", ""))
        if not period_key:
            print(f"warning: period_range が空です。スキップ", file=sys.stderr)
            fail += 1
            continue

        # 対応列を検索
        period_row = all_vals[1] if len(all_vals) > 1 else []
        col_idx = _find_col_for_period(period_row, period_key)
        if col_idx is None:
            print(f"warning: 期間セル一致なし: {repr(period_key[:80])}", file=sys.stderr)
            fail += 1
            if not args.continue_on_error:
                return 1
            continue

        # 行データ生成・書き込み
        row = append_to_sheets.build_row(report)
        col_data = [[v] for v in row]
        row_count = len(append_to_sheets.HEADER)
        start_cell = gspread.utils.rowcol_to_a1(1, col_idx)
        end_cell = gspread.utils.rowcol_to_a1(row_count, col_idx)
        col_letter = gspread.utils.rowcol_to_a1(1, col_idx)[:-1]

        ws.update(col_data, f"{start_cell}:{end_cell}", value_input_option="RAW")
        print(f"info: 列 {col_letter} を上書き完了: {period_key[:40]}", file=sys.stderr)
        ok += 1

        if args.sleep_seconds > 0 and week_mon != week_mons[-1]:
            time.sleep(args.sleep_seconds)

    print(f"\n完了: success={ok}, failed={fail}", file=sys.stderr)
    return 0 if fail == 0 or args.continue_on_error else 1


if __name__ == "__main__":
    raise SystemExit(main())
