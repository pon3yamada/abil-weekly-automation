#!/usr/bin/env python3
"""Google Ads REST API で週次広告指標を集計し、レポート JSON の `google_ads` を埋める。

gRPC ライブラリの互換性問題を避けるため、requests で REST API を直接呼び出す。
"""

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
MICROS = 1_000_000
GOOGLE_ADS_API_VERSION = "v20"


# ── 日付ユーティリティ ─────────────────────────────────────────────────────────

def _reporting_week_monday(anchor: date) -> date:
    """報告対象の「直近で締まった週」の月曜日。"""
    mon_this = anchor - timedelta(days=anchor.weekday())
    return mon_this - timedelta(days=7)


# ── 表示フォーマット（fetch_meta.py と共通パターン） ──────────────────────────

def _delta_class(val: float, prev: float, *, invert: bool = False) -> str:
    """増加が良い指標は invert=False、悪い指標（CPC など）は invert=True。"""
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


# ── OAuth2 アクセストークン取得 ────────────────────────────────────────────────

def _get_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    """リフレッシュトークンからアクセストークンを取得する。"""
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"トークン取得エラー: {data}")
    return data["access_token"]


# ── Google Ads REST API 呼び出し ───────────────────────────────────────────────

def fetch_metrics(customer_id: str, since: str, until: str) -> dict:
    """指定期間のアカウントレベル広告指標をキャンペーン集計で取得する（REST API）。"""
    developer_token = os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"]
    client_id = os.environ["GOOGLE_ADS_CLIENT_ID"]
    client_secret = os.environ["GOOGLE_ADS_CLIENT_SECRET"]
    refresh_token = os.environ["GOOGLE_ADS_REFRESH_TOKEN"]
    login_cid = os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "").strip().replace("-", "")

    access_token = _get_access_token(client_id, client_secret, refresh_token)

    # engagements を含めることで管理画面と同じ CVR を再現
    # CVR = conversions / (clicks + engagements)  ← Google Ads 管理画面の定義
    query = (
        "SELECT metrics.cost_micros, metrics.clicks, metrics.engagements, "
        "metrics.conversions, metrics.conversions_value "
        f"FROM campaign "
        f"WHERE segments.date BETWEEN '{since}' AND '{until}' "
        "AND campaign.status != 'REMOVED'"
    )

    url = (
        f"https://googleads.googleapis.com/{GOOGLE_ADS_API_VERSION}"
        f"/customers/{customer_id}/googleAds:search"
    )
    headers = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": developer_token,
        "Content-Type": "application/json",
    }
    if login_cid:
        headers["login-customer-id"] = login_cid

    total_cost_micros = 0
    total_clicks = 0
    total_engagements = 0
    total_conversions = 0.0
    total_conversions_value = 0.0
    page_token: str | None = None

    while True:
        body: dict = {"query": query}
        if page_token:
            body["pageToken"] = page_token

        resp = requests.post(url, headers=headers, json=body, timeout=30)
        if not resp.ok:
            raise RuntimeError(f"Google Ads API エラー {resp.status_code}: {resp.text}")
        data = resp.json()

        for row in data.get("results", []):
            m = row.get("metrics", {})
            total_cost_micros += int(m.get("costMicros", 0))
            total_clicks += int(m.get("clicks", 0))
            total_engagements += int(m.get("engagements", 0))
            total_conversions += float(m.get("conversions", 0))
            total_conversions_value += float(m.get("conversionsValue", 0))

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    cost = total_cost_micros / MICROS
    # 管理画面と同じ定義: CVR = conversions / (clicks + engagements)
    interactions = total_clicks + total_engagements
    cpc = cost / total_clicks if total_clicks > 0 else 0.0
    cvr = total_conversions / interactions * 100 if interactions > 0 else 0.0
    roas = total_conversions_value / cost if cost > 0 else 0.0

    return {
        "cost": cost,
        "clicks": total_clicks,
        "conversions": total_conversions,
        "conversions_value": total_conversions_value,
        "cpc": cpc,
        "cvr": cvr,
        "roas": roas,
    }


# ── JSON ブロック組み立て ──────────────────────────────────────────────────────

def build_google_metrics(cur: dict, prev: dict) -> dict:
    """cur/prev の指標辞書から google_ads JSON ブロックを組み立てる。"""

    def yen(v: float) -> str:
        return f"¥{int(v):,}"

    cost_cur = cur.get("cost", 0)
    cost_prev = prev.get("cost", 0)
    cv_cur = cur.get("conversions", 0)
    cv_prev = prev.get("conversions", 0)
    cv_val_cur = cur.get("conversions_value", 0)
    cv_val_prev = prev.get("conversions_value", 0)
    clicks_cur = cur.get("clicks", 0)
    clicks_prev = prev.get("clicks", 0)
    cpc_cur = cur.get("cpc", 0)
    cpc_prev = prev.get("cpc", 0)
    cvr_cur = cur.get("cvr", 0)
    cvr_prev = prev.get("cvr", 0)
    roas_cur = cur.get("roas", 0)
    roas_prev = prev.get("roas", 0)
    cpa_cur = cost_cur / cv_cur if cv_cur > 0 else 0
    cpa_prev = cost_prev / cv_prev if cv_prev > 0 else 0

    metrics = [
        {
            "label": "広告費",
            "value": yen(cost_cur),
            "delta": _pct_str(cost_cur, cost_prev),
            "delta_class": _delta_class(cost_cur, cost_prev, invert=True),
        },
        {
            "label": "購入（売上）",
            "value": yen(cv_val_cur),
            "delta": _pct_str(cv_val_cur, cv_val_prev),
            "delta_class": _delta_class(cv_val_cur, cv_val_prev),
        },
        {
            "label": "注文数（CV）",
            "value": f"{int(cv_cur)}件",
            "delta": _pct_str(cv_cur, cv_prev),
            "delta_class": _delta_class(cv_cur, cv_prev),
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

    return {"metrics": metrics}


def update_compare(report: dict, cur: dict) -> None:
    """compare セクション（Meta vs Google の ROAS/CPC/CVR 比較）を更新する。"""
    compare = report.setdefault("compare", {})
    meta = report.get("meta_ads", {})
    m_metrics = {m["label"]: m["value"] for m in meta.get("metrics", [])}

    roas_g = cur.get("roas", 0)
    cpc_g = cur.get("cpc", 0)
    cvr_g = cur.get("cvr", 0)

    # ROAS
    m_roas_str = m_metrics.get("ROAS", "N/A")
    try:
        m_roas = float(m_roas_str.replace("×", ""))
    except ValueError:
        m_roas = 0.0
    max_roas = max(roas_g, m_roas, 0.001)
    compare["roas"] = {
        "caption": f"Meta: {m_roas_str} / Google: {roas_g:.2f}×",
        "meta_bar_pct": round(m_roas / max_roas * 100),
        "google_bar_pct": round(roas_g / max_roas * 100),
        "meta_value": m_roas_str,
        "google_value": f"{roas_g:.2f}×",
    }

    # CPC
    m_cpc_str = m_metrics.get("CPC（クリック単価）", "N/A")
    try:
        m_cpc = float(m_cpc_str.replace("¥", "").replace(",", ""))
    except ValueError:
        m_cpc = 0.0
    max_cpc = max(cpc_g, m_cpc, 0.001)
    compare["cpc"] = {
        "caption": f"Meta: {m_cpc_str} / Google: ¥{int(cpc_g):,}",
        "meta_bar_pct": round(m_cpc / max_cpc * 100),
        "google_bar_pct": round(cpc_g / max_cpc * 100),
        "meta_value": m_cpc_str,
        "google_value": f"¥{int(cpc_g):,}",
    }

    # CVR
    m_cvr_str = m_metrics.get("CVR", "N/A")
    try:
        m_cvr = float(m_cvr_str.replace("%", ""))
    except ValueError:
        m_cvr = 0.0
    max_cvr = max(cvr_g, m_cvr, 0.001)
    compare["cvr"] = {
        "caption": f"Meta: {m_cvr_str} / Google: {cvr_g:.2f}%",
        "meta_bar_pct": round(m_cvr / max_cvr * 100),
        "google_bar_pct": round(cvr_g / max_cvr * 100),
        "meta_value": m_cvr_str,
        "google_value": f"{cvr_g:.2f}%",
    }


# ── エントリポイント ───────────────────────────────────────────────────────────

def main() -> None:
    load_dotenv(ROOT / ".env")

    required_vars = [
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        "GOOGLE_ADS_CLIENT_ID",
        "GOOGLE_ADS_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN",
        "GOOGLE_ADS_CUSTOMER_ID",
    ]
    missing = [v for v in required_vars if not os.environ.get(v, "").strip()]
    if missing:
        print(
            f"ERROR: 以下の環境変数が未設定です: {', '.join(missing)}",
            file=sys.stderr,
        )
        sys.exit(1)

    customer_id = os.environ["GOOGLE_ADS_CUSTOMER_ID"].replace("-", "")

    parser = argparse.ArgumentParser(description="Google Ads 週次指標取得")
    parser.add_argument("--since", help="集計開始日 YYYY-MM-DD（省略時: 直近締め週月曜）")
    parser.add_argument("--until", help="集計終了日 YYYY-MM-DD（省略時: 直近締め週日曜）")
    parser.add_argument(
        "--base",
        default=str(ROOT / "build" / "report_merged.json"),
        help="読み込むベース JSON（省略時: build/report_merged.json）",
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "build" / "report_merged.json"),
        help="出力 JSON（省略時: build/report_merged.json）",
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

    print(f"[Google] 当週: {since_cur} 〜 {until_cur}", file=sys.stderr)
    print(f"[Google] 前週: {since_prev} 〜 {until_prev}", file=sys.stderr)

    # 当週取得
    cur: dict = {}
    try:
        cur = fetch_metrics(customer_id, since_cur, until_cur)
        print(
            f"[Google] 当週 cost={cur['cost']:.0f} clicks={cur['clicks']:.0f} "
            f"cv={cur['conversions']:.0f} ROAS={cur['roas']:.2f}",
            file=sys.stderr,
        )
    except Exception as exc:
        print(f"[Google] 当週取得エラー: {exc}", file=sys.stderr)

    # 前週取得
    prev: dict = {}
    try:
        prev = fetch_metrics(customer_id, since_prev, until_prev)
        print(
            f"[Google] 前週 cost={prev['cost']:.0f} clicks={prev['clicks']:.0f} "
            f"cv={prev['conversions']:.0f} ROAS={prev['roas']:.2f}",
            file=sys.stderr,
        )
    except Exception as exc:
        print(f"[Google] 前週取得エラー: {exc}", file=sys.stderr)

    # ベース JSON 読み込み
    base_path = Path(args.base)
    if base_path.exists():
        report = json.loads(base_path.read_text(encoding="utf-8"))
    else:
        print(f"[Google] ベース JSON が見つかりません: {base_path}", file=sys.stderr)
        report = {"report": {}}

    # google_ads セクション更新
    if cur:
        report["report"]["google_ads"] = build_google_metrics(cur, prev)
        update_compare(report["report"], cur)
        print("[Google] google_ads セクションを更新しました", file=sys.stderr)
    else:
        print("[Google] データ取得失敗のため google_ads は未更新", file=sys.stderr)

    # 出力
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[Google] 出力: {out_path}", file=sys.stderr)

    # stdout にも google_ads を出力（パイプライン確認用）
    print(json.dumps(report["report"].get("google_ads", {}), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
