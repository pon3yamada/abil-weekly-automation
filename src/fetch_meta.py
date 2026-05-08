#!/usr/bin/env python3
"""Meta Marketing API で週次広告指標を集計し、レポート JSON の `meta_ads` を埋める。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
META_API_VERSION = "v21.0"
META_GRAPH_BASE = f"https://graph.facebook.com/{META_API_VERSION}"


# ── 日付ユーティリティ ─────────────────────────────────────────────────────────

def _reporting_week_monday(anchor: date) -> date:
    """報告対象の「直近で締まった週」の月曜日。"""
    mon_this = anchor - timedelta(days=anchor.weekday())
    return mon_this - timedelta(days=7)


# ── 表示フォーマット ───────────────────────────────────────────────────────────

def _delta_class(val: float, prev: float, *, invert: bool = False) -> str:
    """増加が良い指標は invert=False、悪い指標（CPC/CPAなど）は invert=True。"""
    if prev == 0:
        return "metric-neutral"
    pct = (val - prev) / prev
    if abs(pct) < 0.005:
        return "metric-neutral"
    up = pct > 0
    if invert:
        up = not up
    return "metric-up" if up else "metric-down"


def _pct_str(val: float, prev: float) -> str:
    if prev == 0:
        return "→ データなし"
    pct = (val - prev) / prev * 100
    sign = "▲" if pct > 0 else "▼" if pct < 0 else "→"
    return f"{sign} {abs(pct):.1f}% 先週比"


def _pt_str(val: float, prev: float) -> str:
    diff = val - prev
    sign = "▲" if diff > 0 else "▼" if diff < 0 else "→"
    return f"{sign} {abs(diff):.2f}pt 先週比"


def _roas_delta_str(cur: float, prev: float) -> str:
    diff = cur - prev
    sign = "▲" if diff > 0 else "▼" if diff < 0 else "→"
    return f"{sign} {abs(diff):.2f} 先週比"


# ── Meta API 呼び出し ──────────────────────────────────────────────────────────

def fetch_insights(token: str, ad_account_id: str, since: str, until: str) -> dict:
    """指定期間のアカウントレベル広告インサイトを取得する。"""
    url = f"{META_GRAPH_BASE}/{ad_account_id}/insights"
    params = {
        "access_token": token,
        "fields": "spend,clicks,cpc,actions,action_values",
        "time_range": json.dumps({"since": since, "until": until}),
        "level": "account",
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"Meta API エラー: {data['error']}")
    items = data.get("data", [])
    if not items:
        return {}
    return items[0]


def fetch_campaign_insights(token: str, ad_account_id: str, since: str, until: str) -> list[dict]:
    """指定期間のキャンペーン別広告インサイトを取得する。"""
    url = f"{META_GRAPH_BASE}/{ad_account_id}/insights"
    params = {
        "access_token": token,
        "fields": "campaign_name,spend,clicks,actions,action_values",
        "time_range": json.dumps({"since": since, "until": until}),
        "level": "campaign",
        "limit": 50,
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"Meta API エラー（キャンペーン別）: {data['error']}")
    return data.get("data", [])


def _action_value(rows: list[dict], action_type: str) -> float:
    for row in rows or []:
        if row.get("action_type") == action_type:
            return float(row.get("value", 0))
    return 0.0


def parse_insights(raw: dict) -> dict:
    """API レスポンスから指標を抽出・計算する。"""
    spend = float(raw.get("spend", 0))
    clicks = float(raw.get("clicks", 0))
    cpc_raw = raw.get("cpc")
    cpc = float(cpc_raw) if cpc_raw else (spend / clicks if clicks > 0 else 0)

    actions = raw.get("actions", [])
    action_values = raw.get("action_values", [])

    purchases = _action_value(actions, "purchase")
    purchase_value = _action_value(action_values, "purchase")

    roas = purchase_value / spend if spend > 0 else 0
    cvr = purchases / clicks * 100 if clicks > 0 else 0

    return {
        "spend": spend,
        "clicks": clicks,
        "cpc": cpc,
        "purchases": purchases,
        "purchase_value": purchase_value,
        "roas": roas,
        "cvr": cvr,
    }


# ── JSON ブロック組み立て ──────────────────────────────────────────────────────

def build_campaign_rows(raw_campaigns: list[dict]) -> list[dict]:
    """Meta キャンペーン別インサイトからテーブル用データを組み立てる。"""
    rows = []
    for raw in raw_campaigns:
        spend = float(raw.get("spend", 0))
        if spend <= 0:
            continue
        clicks = float(raw.get("clicks", 0))
        actions = raw.get("actions", [])
        action_values = raw.get("action_values", [])
        cv = _action_value(actions, "purchase")
        cv_value = _action_value(action_values, "purchase")
        cpa = spend / cv if cv > 0 else 0
        roas = cv_value / spend if spend > 0 else 0
        rows.append({
            "name": raw.get("campaign_name", "不明"),
            "cost": f"¥{int(spend):,}",
            "cv": f"{int(cv)}件",
            "cpa": f"¥{int(cpa):,}" if cpa > 0 else "—",
            "roas": f"{roas:.2f}×" if roas > 0 else "—",
        })
    rows.sort(key=lambda x: -float(x["cost"].replace("¥", "").replace(",", "")))
    return rows


def build_meta_metrics(cur: dict, prev: dict, campaigns=None) -> dict:
    """cur/prev の指標辞書から meta_ads JSON ブロックを組み立てる。"""

    def yen(v: float) -> str:
        return f"¥{int(v):,}"

    spend_cur = cur.get("spend", 0)
    spend_prev = prev.get("spend", 0)
    purchases_cur = cur.get("purchases", 0)
    purchases_prev = prev.get("purchases", 0)
    pv_cur = cur.get("purchase_value", 0)
    pv_prev = prev.get("purchase_value", 0)
    clicks_cur = cur.get("clicks", 0)
    clicks_prev = prev.get("clicks", 0)
    cpc_cur = cur.get("cpc", 0)
    cpc_prev = prev.get("cpc", 0)
    cvr_cur = cur.get("cvr", 0)
    cvr_prev = prev.get("cvr", 0)
    roas_cur = cur.get("roas", 0)
    roas_prev = prev.get("roas", 0)
    cpa_cur = spend_cur / purchases_cur if purchases_cur > 0 else 0
    cpa_prev = spend_prev / purchases_prev if purchases_prev > 0 else 0

    metrics = [
        {
            "label": "広告費",
            "value": yen(spend_cur),
            "delta": _pct_str(spend_cur, spend_prev),
            "delta_class": _delta_class(spend_cur, spend_prev, invert=True),
        },
        {
            "label": "購入（売上）",
            "value": yen(pv_cur),
            "delta": _pct_str(pv_cur, pv_prev),
            "delta_class": _delta_class(pv_cur, pv_prev),
        },
        {
            "label": "注文数（CV）",
            "value": f"{int(purchases_cur)}件",
            "delta": _pct_str(purchases_cur, purchases_prev),
            "delta_class": _delta_class(purchases_cur, purchases_prev),
        },
        {
            "label": "コンバージョン単価（CPA）",
            "value": yen(cpa_cur),
            "delta": _pct_str(cpa_cur, cpa_prev),
            "delta_class": _delta_class(cpa_cur, cpa_prev, invert=True),
        },
        {
            "label": "クリック数",
            "value": f"{int(clicks_cur):,}",
            "delta": _pct_str(clicks_cur, clicks_prev),
            "delta_class": _delta_class(clicks_cur, clicks_prev),
        },
        {
            "label": "CPC（クリック単価）",
            "value": yen(cpc_cur),
            "delta": _pct_str(cpc_cur, cpc_prev),
            "delta_class": _delta_class(cpc_cur, cpc_prev, invert=True),
        },
        {
            "label": "CVR",
            "value": f"{cvr_cur:.2f}%",
            "delta": _pt_str(cvr_cur, cvr_prev),
            "delta_class": _delta_class(cvr_cur, cvr_prev),
        },
        {
            "label": "ROAS",
            "value": f"{roas_cur:.2f}×",
            "value_class": "text-brand-orange",
            "delta": _roas_delta_str(roas_cur, roas_prev),
            "delta_class": _delta_class(roas_cur, roas_prev),
        },
    ]

    result: dict = {
        "metrics": metrics,
        "_raw": {"cost": spend_cur, "prev_cost": spend_prev, "roas": roas_cur},
    }
    if campaigns is not None:
        result["campaigns"] = campaigns
    return result


def update_compare(report: dict, cur: dict) -> None:
    """compare セクション（Meta vs Google の ROAS/CPC/CVR 比較）を更新する。"""
    compare = report.setdefault("compare", {})
    google = report.get("google_ads", {})
    g_metrics = {m["label"]: m["value"] for m in google.get("metrics", [])}

    roas_m = cur.get("roas", 0)
    cpc_m = cur.get("cpc", 0)
    cvr_m = cur.get("cvr", 0)

    # ROAS
    g_roas_str = g_metrics.get("ROAS", "N/A")
    try:
        g_roas = float(g_roas_str.replace("×", ""))
    except ValueError:
        g_roas = 0
    max_roas = max(roas_m, g_roas, 0.001)
    compare["roas"] = {
        "caption": f"Meta: {roas_m:.2f}× / Google: {g_roas_str}",
        "meta_bar_pct": round(roas_m / max_roas * 100),
        "google_bar_pct": round(g_roas / max_roas * 100),
        "meta_value": f"{roas_m:.2f}×",
        "google_value": g_roas_str,
    }

    # CPC
    g_cpc_str = g_metrics.get("CPC（クリック単価）", "N/A")
    try:
        g_cpc = float(g_cpc_str.replace("¥", "").replace(",", ""))
    except ValueError:
        g_cpc = 0
    max_cpc = max(cpc_m, g_cpc, 0.001)
    compare["cpc"] = {
        "caption": f"Meta: ¥{int(cpc_m):,} / Google: {g_cpc_str}",
        "meta_bar_pct": round(cpc_m / max_cpc * 100),
        "google_bar_pct": round(g_cpc / max_cpc * 100),
        "meta_value": f"¥{int(cpc_m):,}",
        "google_value": g_cpc_str,
    }

    # CVR
    g_cvr_str = g_metrics.get("CVR", "N/A")
    try:
        g_cvr = float(g_cvr_str.replace("%", ""))
    except ValueError:
        g_cvr = 0
    max_cvr = max(cvr_m, g_cvr, 0.001)
    compare["cvr"] = {
        "caption": f"Meta: {cvr_m:.2f}% / Google: {g_cvr_str}",
        "meta_bar_pct": round(cvr_m / max_cvr * 100),
        "google_bar_pct": round(g_cvr / max_cvr * 100),
        "meta_value": f"{cvr_m:.2f}%",
        "google_value": g_cvr_str,
    }


# ── エントリポイント ───────────────────────────────────────────────────────────

def main() -> None:
    load_dotenv(ROOT / ".env")

    token = os.environ.get("META_ACCESS_TOKEN", "")
    ad_account_id = os.environ.get("META_AD_ACCOUNT_ID", "")

    if not token or not ad_account_id:
        print(
            "ERROR: META_ACCESS_TOKEN と META_AD_ACCOUNT_ID を .env に設定してください",
            file=sys.stderr,
        )
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Meta 広告週次指標取得")
    parser.add_argument("--since", help="集計開始日 YYYY-MM-DD（省略時: 直近締め週月曜）")
    parser.add_argument("--until", help="集計終了日 YYYY-MM-DD（省略時: 直近締め週日曜）")
    parser.add_argument(
        "--base",
        default=str(ROOT / "build" / "report_with_shopify.json"),
        help="読み込むベース JSON（省略時: build/report_with_shopify.json）",
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "build" / "report_with_meta.json"),
        help="出力 JSON（省略時: build/report_with_meta.json）",
    )
    args = parser.parse_args()

    # 期間計算
    today = date.today()
    if args.since and args.until:
        since_cur = args.since
        until_cur = args.until
        since_dt = date.fromisoformat(since_cur)
        until_dt = date.fromisoformat(until_cur)
        since_prev = str(since_dt - timedelta(days=7))
        until_prev = str(until_dt - timedelta(days=7))
    else:
        week_mon = _reporting_week_monday(today)
        week_sun = week_mon + timedelta(days=6)
        prev_mon = week_mon - timedelta(days=7)
        prev_sun = prev_mon + timedelta(days=6)
        since_cur, until_cur = str(week_mon), str(week_sun)
        since_prev, until_prev = str(prev_mon), str(prev_sun)

    print(f"[Meta] 当週: {since_cur} 〜 {until_cur}", file=sys.stderr)
    print(f"[Meta] 前週: {since_prev} 〜 {until_prev}", file=sys.stderr)

    # 当週取得
    cur: dict = {}
    try:
        raw_cur = fetch_insights(token, ad_account_id, since_cur, until_cur)
        if raw_cur:
            cur = parse_insights(raw_cur)
            print(
                f"[Meta] 当週 spend={cur['spend']:.0f} clicks={cur['clicks']:.0f} "
                f"purchases={cur['purchases']:.0f} ROAS={cur['roas']:.2f}",
                file=sys.stderr,
            )
        else:
            print("[Meta] 当週: データなし（広告配信なし or 期間外）", file=sys.stderr)
    except Exception as exc:
        print(f"[Meta] 当週取得エラー: {exc}", file=sys.stderr)

    # 前週取得
    prev: dict = {}
    try:
        raw_prev = fetch_insights(token, ad_account_id, since_prev, until_prev)
        if raw_prev:
            prev = parse_insights(raw_prev)
            print(
                f"[Meta] 前週 spend={prev['spend']:.0f} clicks={prev['clicks']:.0f} "
                f"purchases={prev['purchases']:.0f} ROAS={prev['roas']:.2f}",
                file=sys.stderr,
            )
        else:
            print("[Meta] 前週: データなし", file=sys.stderr)
    except Exception as exc:
        print(f"[Meta] 前週取得エラー: {exc}", file=sys.stderr)

    # キャンペーン別取得
    raw_campaigns: list[dict] = []
    try:
        raw_campaigns = fetch_campaign_insights(token, ad_account_id, since_cur, until_cur)
        print(f"[Meta] キャンペーン数: {len(raw_campaigns)}", file=sys.stderr)
    except Exception as exc:
        print(f"[Meta] キャンペーン別取得エラー: {exc}", file=sys.stderr)

    # ベース JSON 読み込み
    base_path = Path(args.base)
    if base_path.exists():
        report = json.loads(base_path.read_text(encoding="utf-8"))
    else:
        print(f"[Meta] ベース JSON が見つかりません: {base_path}", file=sys.stderr)
        report = {"report": {}}

    # meta_ads セクション更新
    if cur:
        campaigns_table = build_campaign_rows(raw_campaigns) if raw_campaigns else None
        report["report"]["meta_ads"] = build_meta_metrics(cur, prev, campaigns=campaigns_table)
        update_compare(report["report"], cur)
        print("[Meta] meta_ads セクションを更新しました", file=sys.stderr)
    else:
        print("[Meta] データ取得失敗のため meta_ads は未更新", file=sys.stderr)

    # 出力
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[Meta] 出力: {out_path}", file=sys.stderr)

    # stdout にも meta_ads を出力（パイプライン確認用）
    print(json.dumps(report["report"].get("meta_ads", {}), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
