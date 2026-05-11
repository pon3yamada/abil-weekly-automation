#!/usr/bin/env python3
"""既存シートの週列だけ、Shopify セッション数・CV率（注文÷セッション）を書き換える。

週ごとに `fetch_shopify.py` だけ実行し、期間セルと一致する列の
`Shopifyセッション数` / `Shopify CV率（%）` 行のみ更新します。
広告データやほかの行はそのままにします。
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

LAB_SESSION = "Shopifyセッション数"
LAB_CVR = "Shopify CV率（%）"


def _last_closed_week_monday(anchor: date) -> date:
    mon_this = anchor - timedelta(days=anchor.weekday())
    return mon_this - timedelta(days=7)


def _week_monday_range(start_mon: date, end_mon: date) -> list[date]:
    if start_mon.weekday() != 0 or end_mon.weekday() != 0:
        raise ValueError("--start-date / --end-date はどちらも月曜である必要があります")
    if end_mon < start_mon:
        raise ValueError("--end-date は --start-date 以降の月曜を指定してください")
    out: list[date] = []
    cur = start_mon
    while cur <= end_mon:
        out.append(cur)
        cur += timedelta(days=7)
    return out


def _period_sheet_value(report_period: str) -> str:
    """`append_to_sheets.build_row` の期間セルと同じ表示にそろえる"""
    return (report_period or "").replace("〜 ", "\n〜 ")


def _find_cols_for_period_from_row2(period_row: list[str], *, period_key: str) -> tuple[int, ...]:
    """2行目（インデックス1）のリストから、一致する列番号を 1 始まりで返す"""

    variants_list = [
        period_key,
        period_key.replace("\n", ""),
        " ".join(period_key.replace("\n", " ").split()),
    ]
    seen: set[str] = set()
    uniq_variants: list[str] = []
    for v in variants_list:
        if v and v not in seen:
            seen.add(v)
            uniq_variants.append(v)

    cols: list[int] = []
    for j0, cell in enumerate(period_row):
        if j0 == 0:
            continue
        for cand in uniq_variants:
            if cand == cell:
                cols.append(j0 + 1)
                break
    return tuple(cols)


def _extract_session_cvr(report: dict) -> tuple[float | None, float | None]:
    metrics = report.get("shopify", {}).get("metrics", [])
    s_str = append_to_sheets._metric_value(metrics, "セッション数")
    c_str = append_to_sheets._metric_value(metrics, "CV率（注文/セッション）")

    session_f: float | None = None
    cvr_f: float | None = None

    if s_str and s_str.strip() not in {"N/A", ""}:
        session_f = float(append_to_sheets._strip_money(s_str.replace(" ", "")))
    if c_str and c_str.strip() not in {"N/A", ""}:
        cvr_f = float(append_to_sheets._strip_pct(c_str.replace(" ", "")))

    return session_f, cvr_f


def main() -> int:
    load_dotenv(ROOT / ".env")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--start-date",
        required=True,
        help="書き換え開始週の月曜 YYYY-MM-DD（例 2023-08-28）",
    )
    parser.add_argument(
        "--end-date",
        default="",
        help="終了週の月曜。省略時は直近締め週の月曜（fetch_shopify と同義）",
    )
    parser.add_argument(
        "--anchor-date",
        default="",
        help="終了月曜を自動決めるときの基準日 YYYY-MM-DD。省略時は今日",
    )
    parser.add_argument(
        "--spreadsheet-id",
        default=os.environ.get("GOOGLE_SHEETS_SPREADSHEET_ID", ""),
        help="スプレッドシート ID（env: GOOGLE_SHEETS_SPREADSHEET_ID）",
    )
    parser.add_argument(
        "--sheet-name",
        default=os.environ.get("GOOGLE_SHEETS_SHEET_NAME", "週次データ"),
        help="シート名（既定: 週次データ）",
    )
    parser.add_argument(
        "--base-template",
        type=Path,
        default=ROOT / "src" / "data" / "sample_report.json",
        help="fetch_shopify の --merge-into 元",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=ROOT / "build" / "patch_shopify_sessions",
        help="週次 JSON の出力先",
    )
    parser.add_argument("--sleep-seconds", type=float, default=0.8)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")

    args = parser.parse_args()

    if not args.spreadsheet_id:
        print(
            "error: --spreadsheet-id または GOOGLE_SHEETS_SPREADSHEET_ID を指定してください",
            file=sys.stderr,
        )
        return 1

    anchor = date.fromisoformat(args.anchor_date) if args.anchor_date else datetime.now().date()
    start_mon = date.fromisoformat(args.start_date)
    if args.end_date:
        end_mon = date.fromisoformat(args.end_date)
    else:
        end_mon = _last_closed_week_monday(anchor)

    week_mons = _week_monday_range(start_mon, end_mon)

    args.work_dir.mkdir(parents=True, exist_ok=True)

    try:
        creds = append_to_sheets._get_credentials()
    except (RuntimeError, json.JSONDecodeError, Exception) as e:
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
    labels_col = [r[0] if r else "" for r in all_vals]
    try:
        row_sess = labels_col.index(LAB_SESSION) + 1
        row_cvr = labels_col.index(LAB_CVR) + 1
    except ValueError:
        print(
            f"error: A列に 『{LAB_SESSION}』『{LAB_CVR}』の行がありません。"
            "`append_to_sheets.py` で一度全体を書いたうえで再実行してください。",
            file=sys.stderr,
        )
        return 1

    if len(all_vals) < 2:
        print("error: シートが2行未満です（期間行がありません）", file=sys.stderr)
        return 1

    ok, fail = 0, 0

    for week_mon in week_mons:
        week_sun = week_mon + timedelta(days=6)
        shopify_anchor = week_mon + timedelta(days=7)
        out_json = args.work_dir / f"report_{week_mon.isoformat()}_{week_sun.isoformat()}.json"

        print(f"\n=== {week_mon.isoformat()} 〜 {week_sun.isoformat()} ===", file=sys.stderr)

        if not args.dry_run:
            cmd = [
                PYTHON,
                str(ROOT / "src" / "fetch_shopify.py"),
                "--anchor-date",
                shopify_anchor.isoformat(),
                "--merge-into",
                str(args.base_template),
                "-o",
                str(out_json),
            ]
            r = subprocess.run(cmd, cwd=ROOT, check=False)
            if r.returncode != 0:
                print(
                    f"warning: fetch_shopify 失敗 exit={r.returncode} 週 {week_mon.isoformat()}",
                    file=sys.stderr,
                )
                fail += 1
                if not args.continue_on_error:
                    return 1
                continue

            doc = json.loads(out_json.read_text(encoding="utf-8"))
            report = doc.get("report", {})
            raw_period = report.get("period_range", "")
            period_key = _period_sheet_value(raw_period)
            sess_v, cvr_v = _extract_session_cvr(report)

            row2 = all_vals[1]

            cols = _find_cols_for_period_from_row2(row2, period_key=period_key)

            if not cols:
                print(
                    f"warning: 期間セル一致なし: {repr(period_key[:80])}",
                    file=sys.stderr,
                )
                fail += 1
                if not args.continue_on_error:
                    return 1
                continue

            if sess_v is None and cvr_v is None:
                print(f"warning: セッション/CV率とも取得不可（この週はスキップ）", file=sys.stderr)
                fail += 1
                if not args.continue_on_error:
                    return 1
                continue

            for wc in cols:
                if sess_v is not None:
                    ws.update_cell(row_sess, wc, sess_v)
                if cvr_v is not None:
                    ws.update_cell(row_cvr, wc, cvr_v)
                print(
                    f"info: 列 {wc} にセッション={sess_v!s} CV率={cvr_v!s}",
                    file=sys.stderr,
                )
            ok += 1

            if (
                args.sleep_seconds > 0
                and week_mon != week_mons[-1]
            ):
                time.sleep(args.sleep_seconds)
        else:
            print(f"dry-run 週 {week_mon.isoformat()} anchor→{shopify_anchor}", file=sys.stderr)
            ok += 1

    print(f"\n完了: patched≈success={ok}, failed={fail}", file=sys.stderr)
    return 0 if fail == 0 or args.continue_on_error else 1


if __name__ == "__main__":
    raise SystemExit(main())
