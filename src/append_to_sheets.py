#!/usr/bin/env python3
"""Google Sheets に週次レポートデータを 1 行追記する。

認証は Service Account JSON を使用する。
環境変数 GOOGLE_SHEETS_CREDENTIALS に JSON 文字列を渡すか、
GOOGLE_SHEETS_CREDENTIALS_FILE にファイルパスを指定する。

使い方:
    python3 src/append_to_sheets.py \\
        --base build/report_merged.json \\
        --spreadsheet-id <SPREADSHEET_ID> \\
        [--sheet-name "週次データ"]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

HEADER = [
    # 管理情報
    "生成日時",
    "期間",
    # サマリー
    "売上（円）",
    "広告費合計（円）",
    "MER（%）",
    # Shopify セクション
    "── Shopify ──",
    "注文件数",
    "Shopify売上（円）",
    "AOV（円）",
    "既存顧客比率（%）",
    # Meta セクション
    "── Meta広告 ──",
    "Meta広告費（円）",
    "Meta CV数",
    "Meta CPA（円）",
    "Metaクリック数",
    "Meta CPC（円）",
    "Meta CVR（%）",
    "Meta ROAS",
    # Google セクション
    "── Google広告 ──",
    "Google広告費（円）",
    "Google CV数",
    "Google CPA（円）",
    "Googleクリック数",
    "Google CPC（円）",
    "Google CVR（%）",
    "Google ROAS",
]


# ── パーサーユーティリティ ─────────────────────────────────────────────────────

def _strip_money(s: str) -> float:
    """'¥132,502' → 132502.0"""
    try:
        return float(s.replace("¥", "").replace(",", "").strip())
    except (ValueError, AttributeError):
        return 0.0


def _strip_pct(s: str) -> float:
    """'38.7%' → 38.7"""
    try:
        return float(s.replace("%", "").strip())
    except (ValueError, AttributeError):
        return 0.0


def _strip_roas(s: str) -> float:
    """'1.75×' → 1.75"""
    try:
        return float(s.replace("×", "").strip())
    except (ValueError, AttributeError):
        return 0.0


def _metric_value(metrics: list[dict], label: str) -> str:
    """metrics リストからラベルに一致する value を返す。"""
    for m in metrics:
        if m.get("label") == label:
            return m.get("value", "")
    return ""


# ── JSON → 行データ変換 ───────────────────────────────────────────────────────

def build_row(report: dict) -> list:
    """report JSON から Sheets 書き込み用の行リストを生成する。"""
    period = report.get("period_range", "").replace("〜 ", "\n〜 ")

    # ── サマリー
    summary = report.get("summary", {})
    sales_str = summary.get("sales", {}).get("value", "")
    ad_spend_str = summary.get("ad_spend", {}).get("value", "")
    mer_str = summary.get("mer", {}).get("value", "")

    sales_raw = _strip_money(sales_str)
    ad_spend_raw = _strip_money(ad_spend_str)
    mer_raw = _strip_pct(mer_str)

    # ── Shopify
    shopify_metrics = report.get("shopify", {}).get("metrics", [])
    sh_orders = _metric_value(shopify_metrics, "注文件数")
    sh_revenue = _metric_value(shopify_metrics, "週次売上（税込）")
    sh_aov = _metric_value(shopify_metrics, "平均注文単価")
    sh_repeat = _metric_value(shopify_metrics, "既存顧客による注文の割合")

    sh_orders_raw = _strip_money(sh_orders)  # 数値文字列そのまま
    sh_revenue_raw = _strip_money(sh_revenue)
    sh_aov_raw = _strip_money(sh_aov)
    sh_repeat_raw = _strip_pct(sh_repeat)

    # ── Meta
    meta_raw = report.get("meta_ads", {}).get("_raw", {})
    meta_cost = float(meta_raw.get("cost", 0))
    meta_roas = float(meta_raw.get("roas", 0))
    meta_metrics = report.get("meta_ads", {}).get("metrics", [])

    meta_cv_str = _metric_value(meta_metrics, "注文数（CV）")
    meta_cpa_str = _metric_value(meta_metrics, "コンバージョン単価（CPA）")
    meta_clicks_str = _metric_value(meta_metrics, "クリック数")
    meta_cpc_str = _metric_value(meta_metrics, "CPC（クリック単価）")
    meta_cvr_str = _metric_value(meta_metrics, "CVR")

    meta_cv = int(_strip_money(meta_cv_str.replace("件", ""))) if meta_cv_str else 0
    meta_cpa = _strip_money(meta_cpa_str)
    meta_clicks = int(_strip_money(meta_clicks_str.replace(",", ""))) if meta_clicks_str else 0
    meta_cpc = _strip_money(meta_cpc_str)
    meta_cvr = _strip_pct(meta_cvr_str)

    # ── Google
    google_raw = report.get("google_ads", {}).get("_raw", {})
    google_cost = float(google_raw.get("cost", 0))
    google_roas = float(google_raw.get("roas", 0))
    google_metrics = report.get("google_ads", {}).get("metrics", [])

    google_cv_str = _metric_value(google_metrics, "注文数（CV）")
    google_cpa_str = _metric_value(google_metrics, "コンバージョン単価（CPA）")
    google_clicks_str = _metric_value(google_metrics, "クリック数")
    google_cpc_str = _metric_value(google_metrics, "CPC（クリック単価）")
    google_cvr_str = _metric_value(google_metrics, "CVR")

    google_cv = int(_strip_money(google_cv_str.replace("件", ""))) if google_cv_str else 0
    google_cpa = _strip_money(google_cpa_str)
    google_clicks = int(_strip_money(google_clicks_str.replace(",", ""))) if google_clicks_str else 0
    google_cpc = _strip_money(google_cpc_str)
    google_cvr = _strip_pct(google_cvr_str)

    now_jst = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    return [
        # 管理情報
        now_jst,
        period,
        # サマリー
        sales_raw,
        ad_spend_raw,
        mer_raw,
        # Shopify セクション（スペーサー行は空文字）
        "",
        sh_orders_raw,
        sh_revenue_raw,
        sh_aov_raw,
        sh_repeat_raw,
        # Meta セクション
        "",
        meta_cost,
        meta_cv,
        meta_cpa,
        meta_clicks,
        meta_cpc,
        meta_cvr,
        meta_roas,
        # Google セクション
        "",
        google_cost,
        google_cv,
        google_cpa,
        google_clicks,
        google_cpc,
        google_cvr,
        google_roas,
    ]


# ── Google Sheets 認証 ────────────────────────────────────────────────────────

def _get_credentials() -> Credentials:
    """環境変数から Service Account 認証情報を取得する。

    優先順位:
      1. GOOGLE_SHEETS_CREDENTIALS  (JSON 文字列)
      2. GOOGLE_SHEETS_CREDENTIALS_FILE  (ファイルパス)
    """
    creds_json = os.environ.get("GOOGLE_SHEETS_CREDENTIALS", "").strip()
    if creds_json:
        info = json.loads(creds_json)
        return Credentials.from_service_account_info(info, scopes=SCOPES)

    creds_file = os.environ.get("GOOGLE_SHEETS_CREDENTIALS_FILE", "").strip()
    if creds_file:
        return Credentials.from_service_account_file(creds_file, scopes=SCOPES)

    raise RuntimeError(
        "Service Account 認証情報が見つかりません。\n"
        "  GOOGLE_SHEETS_CREDENTIALS または GOOGLE_SHEETS_CREDENTIALS_FILE を設定してください。"
    )


# ── メイン ────────────────────────────────────────────────────────────────────

def main() -> int:
    load_dotenv(ROOT / ".env")

    parser = argparse.ArgumentParser(description="週次レポートデータを Google Sheets に追記する")
    parser.add_argument(
        "--base", "-b",
        type=Path,
        default=ROOT / "build" / "report_merged.json",
        help="マージ済みレポート JSON（デフォルト: build/report_merged.json）",
    )
    parser.add_argument(
        "--spreadsheet-id",
        default=os.environ.get("GOOGLE_SHEETS_SPREADSHEET_ID", ""),
        help="Google Sheets のスプレッドシート ID（env: GOOGLE_SHEETS_SPREADSHEET_ID）",
    )
    parser.add_argument(
        "--sheet-name",
        default=os.environ.get("GOOGLE_SHEETS_SHEET_NAME", "週次データ"),
        help="書き込み先シート名（デフォルト: 週次データ）",
    )
    args = parser.parse_args()

    if not args.spreadsheet_id:
        print("error: --spreadsheet-id または GOOGLE_SHEETS_SPREADSHEET_ID を指定してください", file=sys.stderr)
        return 1

    # JSON 読み込み
    try:
        doc = json.loads(args.base.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"error: JSON 読み込み失敗: {e}", file=sys.stderr)
        return 1

    report = doc.get("report", {})
    if not report:
        print("error: JSON に report キーがありません", file=sys.stderr)
        return 1

    # 行データ生成
    row = build_row(report)
    period = row[0]

    # Sheets 認証
    try:
        creds = _get_credentials()
    except (RuntimeError, json.JSONDecodeError, Exception) as e:
        print(f"error: 認証情報の取得に失敗: {e}", file=sys.stderr)
        return 1

    gc = gspread.authorize(creds)

    try:
        spreadsheet = gc.open_by_key(args.spreadsheet_id)
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"error: スプレッドシート '{args.spreadsheet_id}' が見つかりません", file=sys.stderr)
        return 1

    # シートを取得（なければ作成）
    try:
        ws = spreadsheet.worksheet(args.sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=args.sheet_name, rows=len(HEADER) + 2, cols=60)
        print(f"info: シート '{args.sheet_name}' を新規作成しました")

    # ────────────────────────────────────────────────────────────────
    # 縦レイアウト（転置形式）
    #   A列      = 指標名（ラベル列）
    #   B列以降  = 週ごとのデータ列（新しい週 = 新しい列）
    #
    #   行1: 期間
    #   行2: 売上（円）
    #   行3: 広告費合計（円）
    #   ...
    # ────────────────────────────────────────────────────────────────
    existing = ws.get_all_values()
    row_count = len(HEADER)

    # A列（ラベル列）がなければ書き込む
    label_col = [r[0] if r else "" for r in existing]
    expected_labels = HEADER  # HEADER をそのまま行ラベルとして使う
    if label_col != expected_labels:
        label_updates = [[lbl] for lbl in expected_labels]
        ws.update(label_updates, "A1")
        print("info: A列（指標ラベル）を書き込みました")
        existing = ws.get_all_values()

    # 既存データ列から同一期間を探す（1行目 = 期間行）
    # 列 B 以降（インデックス 1 以降）を検索
    period_row = existing[0] if existing else []
    match_col_idx = None  # 0-indexed (0=A, 1=B, ...)
    for col_i, cell_val in enumerate(period_row):
        if col_i == 0:
            continue  # A列はラベル列なのでスキップ
        if cell_val == period:
            match_col_idx = col_i
            break

    # 書き込む列を決定：一致あり → 上書き、なし → 次の空き列
    if match_col_idx is not None:
        write_col = match_col_idx + 1  # gspread は 1-indexed
        print(f"info: 既存列（{gspread.utils.rowcol_to_a1(1, write_col)[:-1]} 列）を上書きします: {period}")
    else:
        # 次の空き列 = period_row の長さ + 1（A列が既にあるので最低 2）
        write_col = max(len(period_row) + 1, 2)
        print(f"info: 新規列（{gspread.utils.rowcol_to_a1(1, write_col)[:-1]} 列）に追記します: {period}")

    # 書き込み：各値を縦に並べる
    col_data = [[v] for v in row]  # row の各要素を 1 行ずつに変換
    start_cell = gspread.utils.rowcol_to_a1(1, write_col)
    end_cell = gspread.utils.rowcol_to_a1(row_count, write_col)
    ws.update(col_data, f"{start_cell}:{end_cell}", value_input_option="RAW")

    print(f"完了: スプレッドシート ID={args.spreadsheet_id}, シート='{args.sheet_name}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
