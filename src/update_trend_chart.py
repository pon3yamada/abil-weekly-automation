#!/usr/bin/env python3
"""過去数週のAPI実データで `report.trend_chart` を更新する。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

import fetch_google_ads
import fetch_meta
import fetch_shopify

ROOT = Path(__file__).resolve().parents[1]


def _week_label(week_mon: date, *, is_current: bool) -> str:
    label = f"{week_mon.month}/{week_mon.day}週"
    return f"{label}（今週）" if is_current else label


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"report": {}}


def _fetch_shopify_week_revenue(
    *,
    week_mon: date,
    host: str,
    api_version: str,
    session,
    tz_name: str,
    include_test: bool,
    paid_only: bool,
) -> Decimal:
    start_utc, end_utc = fetch_shopify._week_inclusive_utc_bounds(week_mon, tz_name)
    orders = list(
        fetch_shopify.iter_orders_created_between(
            session,
            fetch_shopify._rest_base(host, api_version),
            start_utc,
            end_utc,
            include_test=include_test,
            financial_status="paid" if paid_only else None,
        )
    )
    return fetch_shopify.aggregate_week(
        orders,
        week_start_utc=start_utc,
        customer_created={},
    )["revenue"]


def _fetch_meta_cost(token: str, ad_account_id: str, since: str, until: str) -> float:
    raw = fetch_meta.fetch_insights(token, ad_account_id, since, until)
    return fetch_meta.parse_insights(raw).get("spend", 0.0) if raw else 0.0


def build_trend_chart(
    *,
    anchor: date,
    weeks: int,
    include_test: bool,
    paid_only: bool,
    allow_partial: bool,
) -> dict:
    if weeks <= 0:
        raise ValueError("--weeks は1以上を指定してください")

    shop_raw = os.environ.get("SHOPIFY_STORE", "").strip()
    shop_token = os.environ.get("SHOPIFY_ACCESS_TOKEN", "").strip()
    if not shop_raw or not shop_token:
        raise RuntimeError("SHOPIFY_STORE と SHOPIFY_ACCESS_TOKEN を設定してください")

    meta_token = os.environ.get("META_ACCESS_TOKEN", "").strip()
    meta_account_id = os.environ.get("META_AD_ACCOUNT_ID", "").strip()
    google_customer_id = os.environ.get("GOOGLE_ADS_CUSTOMER_ID", "").strip().replace("-", "")

    host = fetch_shopify._normalize_shop_host(shop_raw)
    api_version = (
        os.environ.get("SHOPIFY_API_VERSION", fetch_shopify.DEFAULT_API_VERSION).strip()
        or fetch_shopify.DEFAULT_API_VERSION
    )
    shop_session = fetch_shopify._session(shop_token)
    shop_base = fetch_shopify._rest_base(host, api_version)
    tz_name, _currency = fetch_shopify.fetch_shop_timezone_and_currency(shop_session, shop_base)

    report_mon = fetch_shopify._reporting_week_monday(anchor)
    week_starts = [report_mon - timedelta(days=7 * i) for i in reversed(range(weeks))]

    labels: list[str] = []
    sales: list[int] = []
    ad_spend: list[int] = []
    roas: list[float] = []

    for week_mon in week_starts:
        week_sun = week_mon + timedelta(days=6)
        since = week_mon.isoformat()
        until = week_sun.isoformat()

        try:
            revenue = _fetch_shopify_week_revenue(
                week_mon=week_mon,
                host=host,
                api_version=api_version,
                session=shop_session,
                tz_name=tz_name,
                include_test=include_test,
                paid_only=paid_only,
            )
        except Exception:
            if not allow_partial:
                raise
            print(f"[Trend] Shopify取得失敗: {since}〜{until}", file=sys.stderr)
            revenue = Decimal(0)

        meta_cost = 0.0
        if meta_token and meta_account_id:
            try:
                meta_cost = _fetch_meta_cost(meta_token, meta_account_id, since, until)
            except Exception as exc:
                if not allow_partial:
                    raise
                print(f"[Trend] Meta取得失敗: {since}〜{until}: {exc}", file=sys.stderr)

        google_cost = 0.0
        if google_customer_id:
            try:
                google_cost = fetch_google_ads.fetch_metrics(google_customer_id, since, until).get("cost", 0.0)
            except Exception as exc:
                if not allow_partial:
                    raise
                print(f"[Trend] Google取得失敗: {since}〜{until}: {exc}", file=sys.stderr)

        total_ad_spend = meta_cost + google_cost
        revenue_int = int(revenue)
        ad_spend_int = int(total_ad_spend)

        labels.append(_week_label(week_mon, is_current=week_mon == report_mon))
        sales.append(revenue_int)
        ad_spend.append(ad_spend_int)
        roas.append(round(revenue_int / total_ad_spend, 2) if total_ad_spend > 0 else 0.0)

        print(
            f"[Trend] {since}〜{until}: sales=¥{revenue_int:,} "
            f"ad_spend=¥{ad_spend_int:,} roas={roas[-1]:.2f}",
            file=sys.stderr,
        )

    return {
        "labels": labels,
        "sales": sales,
        "ad_spend": ad_spend,
        "roas": roas,
    }


def main() -> int:
    load_dotenv(ROOT / ".env")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", "-b", type=Path, default=ROOT / "build" / "report_merged.json")
    parser.add_argument("--out", "-o", type=Path, default=ROOT / "build" / "report_merged.json")
    parser.add_argument("--weeks", type=int, default=4)
    parser.add_argument("--anchor-date", default="", help="基準日 YYYY-MM-DD。未指定なら実行日")
    parser.add_argument("--include-test", action="store_true", help="Shopifyのテスト注文を含める")
    parser.add_argument("--paid-only", action="store_true", help="Shopifyのpaid注文のみ集計")
    parser.add_argument("--allow-partial", action="store_true", help="一部API失敗時も0扱いで出力する")
    args = parser.parse_args()

    anchor = date.fromisoformat(args.anchor_date) if args.anchor_date else datetime.now().date()
    doc = _load_json(args.base)
    report = doc.setdefault("report", {})
    report["trend_chart"] = build_trend_chart(
        anchor=anchor,
        weeks=args.weeks,
        include_test=args.include_test,
        paid_only=args.paid_only,
        allow_partial=args.allow_partial,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[Trend] 出力: {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
