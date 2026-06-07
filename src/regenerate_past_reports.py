#!/usr/bin/env python3
"""過去週の HTML レポートを正しいデータで再生成する。

タイムゾーンずれで誤った広告データが含まれていた週を対象に、
完全パイプライン（Shopify→Meta→Google→Trend→Alerts→Actions→HTML）を
ローカルで実行し、_site/<slug>/index.html と reports_index.json を更新します。

使い方:
    python3 src/regenerate_past_reports.py \\
        --start-date 2026-05-18 \\
        --end-date   2026-06-01 \\
        --dry-run
    # 確認後に --dry-run を外して本実行
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PYTHON = sys.executable or "python3"


def _week_monday_range(start_mon: date, end_mon: date) -> list[date]:
    if start_mon.weekday() != 0 or end_mon.weekday() != 0:
        raise ValueError("--start-date / --end-date はどちらも月曜 (weekday=0) である必要があります")
    out: list[date] = []
    cur = start_mon
    while cur <= end_mon:
        out.append(cur)
        cur += timedelta(days=7)
    return out


def _slug_from_period(period_range: str) -> str | None:
    nums = re.findall(r"(\d{4})年(\d{1,2})月(\d{1,2})日", period_range)
    if len(nums) < 2:
        return None
    s = f"{nums[0][0][2:]}{int(nums[0][1]):02d}{int(nums[0][2]):02d}"
    e = f"{nums[1][0][2:]}{int(nums[1][1]):02d}{int(nums[1][2]):02d}"
    return f"weekly_report_{s}-{e}"


def run_cmd(label: str, cmd: list[str], *, check: bool = False, dry_run: bool = False) -> bool:
    if dry_run:
        print(f"[dry-run] {label}: {' '.join(cmd)}", file=sys.stderr)
        return True
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if r.stdout.strip():
        print(r.stdout, file=sys.stderr)
    if r.returncode != 0:
        print(f"[{label}] FAILED exit={r.returncode}\n{r.stderr}", file=sys.stderr)
        return False
    if r.stderr.strip():
        print(r.stderr, file=sys.stderr)
    print(f"[{label}] OK", file=sys.stderr)
    return True


def process_week(week_mon: date, work_dir: Path, base_template: Path, *, dry_run: bool, soft_fail_actions: bool) -> bool:
    week_sun = week_mon + timedelta(days=6)
    anchor = (week_mon + timedelta(days=7)).isoformat()
    since = week_mon.isoformat()
    until = week_sun.isoformat()
    merged = work_dir / f"merged_{since}_{until}.json"
    label = f"{since} 〜 {until}"

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"=== {label} ===", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    # 1. Shopify
    ok = run_cmd("Shopify", [
        PYTHON, str(SRC / "fetch_shopify.py"),
        "--anchor-date", anchor,
        "--merge-into", str(base_template),
        "-o", str(merged),
    ], dry_run=dry_run)
    if not ok:
        return False

    # 2. Meta
    run_cmd("Meta", [
        PYTHON, str(SRC / "fetch_meta.py"),
        "--since", since, "--until", until,
        "--base", str(merged), "--out", str(merged),
    ], dry_run=dry_run)  # 失敗しても続行

    # 3. Google
    run_cmd("Google", [
        PYTHON, str(SRC / "fetch_google_ads.py"),
        "--since", since, "--until", until,
        "--base", str(merged), "--out", str(merged),
    ], dry_run=dry_run)  # 失敗しても続行

    # 4. Trend chart（過去4週）
    run_cmd("Trend", [
        PYTHON, str(SRC / "update_trend_chart.py"),
        "--base", str(merged), "--out", str(merged),
        "--anchor-date", anchor,
        "--weeks", "4",
        "--allow-partial",
    ], dry_run=dry_run)  # 失敗しても続行

    # 5. Alerts + Score
    ok = run_cmd("Alerts", [
        PYTHON, str(SRC / "generate_alerts.py"),
        "--base", str(merged), "--out", str(merged),
    ], dry_run=dry_run)
    if not ok:
        return False

    # 6. LLM Actions（soft-fail）
    actions_cmd = [
        PYTHON, str(SRC / "generate_actions.py"),
        "--base", str(merged), "--out", str(merged),
    ]
    if soft_fail_actions:
        actions_cmd.append("--soft-fail")
    run_cmd("Actions", actions_cmd, dry_run=dry_run)  # 失敗しても続行

    if dry_run:
        print(f"[dry-run] HTML 生成 → _site/<slug>/index.html", file=sys.stderr)
        print(f"[dry-run] reports_index.json 更新", file=sys.stderr)
        return True

    # slug を決定
    doc = json.loads(merged.read_text(encoding="utf-8"))
    report = doc.get("report", {})
    period_range = report.get("period_range", "")
    slug = _slug_from_period(period_range)
    if not slug:
        print(f"error: period_range から slug を決定できませんでした: {period_range!r}", file=sys.stderr)
        return False
    print(f"[slug] {slug}", file=sys.stderr)

    # 7. HTML 生成
    html_out = ROOT / "_site" / slug / "index.html"
    html_out.parent.mkdir(parents=True, exist_ok=True)
    ok = run_cmd("HTML", [
        PYTHON, str(SRC / "generate_report.py"),
        "-i", str(merged),
        "-o", str(html_out),
    ], dry_run=dry_run)
    if not ok:
        return False
    if not html_out.exists() or html_out.stat().st_size == 0:
        print(f"error: HTML が空または未生成: {html_out}", file=sys.stderr)
        return False
    print(f"[HTML] 出力: {html_out} ({html_out.stat().st_size:,} bytes)", file=sys.stderr)

    # 8. reports_index.json 更新
    idx_path = SRC / "data" / "reports_index.json"
    reports = json.loads(idx_path.read_text(encoding="utf-8"))
    now_jst = datetime.now(ZoneInfo("Asia/Tokyo"))
    now_str = f"{now_jst.year}年{now_jst.month}月{now_jst.day}日 {now_jst.hour:02d}:{now_jst.minute:02d}"
    entry = {
        "slug": slug,
        "period": period_range,
        "generated_at": now_str,
        "overall_score": report.get("overall_score") or "—",
        "score_subtitle": report.get("score_subtitle") or "",
    }
    reports = [r for r in reports if r.get("slug") != slug]
    reports.append(entry)
    # slug の昇順でソートして保存
    reports.sort(key=lambda r: r.get("slug", ""))
    idx_path.write_text(json.dumps(reports, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[Index] reports_index.json 更新: {slug} score={entry['overall_score']}", file=sys.stderr)

    return True


def main() -> int:
    load_dotenv(ROOT / ".env")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", required=True, help="再生成開始週の月曜 YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="再生成終了週の月曜 YYYY-MM-DD")
    parser.add_argument(
        "--base-template",
        type=Path,
        default=SRC / "data" / "sample_report.json",
        help="fetch_shopify の --merge-into 元",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=ROOT / "build" / "regenerate",
        help="中間 JSON の出力先",
    )
    parser.add_argument("--no-soft-fail-actions", action="store_true", help="LLM アクション失敗時に中止する")
    parser.add_argument("--dry-run", action="store_true", help="実際の処理を行わず手順だけ表示")
    parser.add_argument("--continue-on-error", action="store_true", help="週単位の失敗を無視して続行")
    args = parser.parse_args()

    start_mon = date.fromisoformat(args.start_date)
    end_mon = date.fromisoformat(args.end_date)
    week_mons = _week_monday_range(start_mon, end_mon)
    args.work_dir.mkdir(parents=True, exist_ok=True)

    print(f"対象週: {[str(m) for m in week_mons]}", file=sys.stderr)

    ok, fail = 0, 0
    for week_mon in week_mons:
        success = process_week(
            week_mon,
            args.work_dir,
            args.base_template,
            dry_run=args.dry_run,
            soft_fail_actions=not args.no_soft_fail_actions,
        )
        if success:
            ok += 1
        else:
            fail += 1
            if not args.continue_on_error:
                print("中断します（--continue-on-error で無視可）", file=sys.stderr)
                return 1

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"完了: success={ok}, failed={fail}", file=sys.stderr)
    return 0 if fail == 0 or args.continue_on_error else 1


if __name__ == "__main__":
    raise SystemExit(main())
