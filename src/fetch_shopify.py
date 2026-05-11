#!/usr/bin/env python3
"""Shopify Admin API（注文ベース）で週次指標を集計し、レポート JSON の `shopify` を埋める。"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
# ShopifyQL の `shopifyqlQuery` に合わせ 2025-10 以降を既定にする（未設定時）
DEFAULT_API_VERSION = "2025-10"


def _jp_weekday(d: date) -> str:
    return "月火水木金土日"[d.weekday()]


def _format_period_jp(week_mon: date) -> str:
    week_sun = week_mon + timedelta(days=6)
    return (
        f"{week_mon.year}年{week_mon.month}月{week_mon.day}日（{_jp_weekday(week_mon)}）〜 "
        f"{week_sun.year}年{week_sun.month}月{week_sun.day}日（{_jp_weekday(week_sun)}）"
    )


def _reporting_week_monday(anchor: date) -> date:
    """報告対象の「直近で締まった週」の月曜日（店舗ローカル日付）。"""
    mon_this = anchor - timedelta(days=anchor.weekday())
    return mon_this - timedelta(days=7)


def _week_inclusive_utc_bounds(week_mon: date, tz_name: str) -> tuple[datetime, datetime]:
    """週の月曜 00:00 〜 日曜 23:59:59（店舗 TZ）を UTC に変換。"""
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(tz_name)
    start_local = datetime.combine(week_mon, time.min, tzinfo=tz)
    sun = week_mon + timedelta(days=6)
    end_local = datetime.combine(sun, time(23, 59, 59), tzinfo=tz)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _iso_utc_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _next_page_url(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        if 'rel="next"' in part:
            url = part.split(";")[0].strip()
            if url.startswith("<") and url.endswith(">"):
                return url[1:-1]
    return None


def _admin_api_version_tuple(api_version: str) -> tuple[int, int] | None:
    m = re.fullmatch(r"(\d{4})-(\d{2})", api_version.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _supports_shopifyql_admin_query(api_version: str) -> bool:
    """GraphQL の `shopifyqlQuery` は Admin API 2025-10 以降。"""
    t = _admin_api_version_tuple(api_version)
    if t is None:
        return True
    return t >= (2025, 10)


def _normalize_shop_host(raw: str) -> str:
    s = raw.strip().lower()
    s = re.sub(r"^https?://", "", s)
    s = s.rstrip("/")
    return s


def _session(token: str) -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "X-Shopify-Access-Token": token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
    )
    return s


def _rest_base(host: str, api_version: str) -> str:
    return f"https://{host}/admin/api/{api_version}"


def iter_orders_created_between(
    sess: requests.Session,
    base: str,
    created_min_utc: datetime,
    created_max_inclusive_utc: datetime,
    *,
    include_test: bool,
    financial_status: str | None,
) -> Iterable[dict[str, Any]]:
    params: dict[str, Any] = {
        "status": "any",
        "limit": 250,
        "created_at_min": _iso_utc_z(created_min_utc),
        "created_at_max": _iso_utc_z(created_max_inclusive_utc),
    }
    if financial_status:
        params["financial_status"] = financial_status

    url = f"{base}/orders.json"
    first = True
    while url:
        if first:
            r = sess.get(url, params=params, timeout=60)
            first = False
        else:
            r = sess.get(url, timeout=60)
        r.raise_for_status()
        for o in r.json().get("orders", []):
            if not include_test and o.get("test"):
                continue
            yield o
        url = _next_page_url(r.headers.get("Link"))


def fetch_sessions_shopifyql(
    sess: requests.Session,
    host: str,
    api_version: str,
    date_from: date,
    date_to: date,
) -> int | None:
    """ShopifyQL（GraphQL `shopifyqlQuery`）でセッション数を集計する。

    Admin API **2025-10 以降**と **`read_reports`** スコープが必要
    （`read_analytics` のみでは取得できないことがあります）。

    取得不可時は None（呼び出し側ではセッション・CV率を N/A 表示）。
    """
    if not _supports_shopifyql_admin_query(api_version):
        print(
            "warning: セッション数は GraphQL の shopifyqlQuery が必要です。"
            "SHOPIFY_API_VERSION を **2025-10 以降**にしてください（例: 2025-10）。",
            file=sys.stderr,
        )
        return None

    gql_url = f"https://{host}/admin/api/{api_version}/graphql.json"
    # ShopifyQL: FROM と SHOW が必須（https://shopify.dev/docs/api/shopifyql）
    query_str = (
        "FROM sessions\n"
        "  SHOW sessions\n"
        f"  SINCE {date_from.isoformat()} UNTIL {date_to.isoformat()}"
    )
    graphql_query = """
    query SessionAgg($qs: String!) {
      shopifyqlQuery(query: $qs) {
        parseErrors
        tableData {
          columns {
            name
          }
          rows
        }
      }
    }
    """
    try:
        r = sess.post(
            gql_url,
            json={"query": graphql_query, "variables": {"qs": query_str}},
            timeout=60,
        )
        r.raise_for_status()
        body = r.json()
    except requests.HTTPError as e:
        print(f"warning: セッション数取得に失敗（HTTP {e.response.status_code}）、スキップします", file=sys.stderr)
        return None
    except Exception as e:
        print(f"warning: セッション数取得に失敗: {e}", file=sys.stderr)
        return None

    if body.get("errors"):
        print(f"warning: セッション数 GraphQL エラー: {body['errors']}", file=sys.stderr)
        return None

    sq = (body.get("data") or {}).get("shopifyqlQuery")
    if sq is None:
        print(
            "warning: GraphQL が shopifyqlQuery を返していません。"
            "API バージョンと read_reports スコープ・再インストールを確認してください。",
            file=sys.stderr,
        )
        return None

    parse_errors = sq.get("parseErrors") or []
    if parse_errors:
        print(f"warning: ShopifyQL の parseErrors: {parse_errors}", file=sys.stderr)
        return None

    table_data = sq.get("tableData") or {}
    rows_raw = table_data.get("rows")
    if rows_raw is None:
        rows: list[Any] = []
    elif isinstance(rows_raw, list):
        rows = rows_raw
    else:
        rows = []

    metric_keys = ("sessions", "Sessions", "total_sessions", "session_count")
    total = 0
    parsed = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        val: Any = None
        for key in metric_keys:
            if key in row:
                val = row[key]
                break
        if val is None:
            lk = {k.lower(): k for k in row}
            for key in metric_keys:
                kl = key.lower()
                if kl in lk:
                    val = row[lk[kl]]
                    break
        if val is None:
            continue
        try:
            total += int(round(float(str(val))))
            parsed = True
        except (ValueError, TypeError):
            continue

    if not parsed:
        if rows:
            print(
                "warning: セッション数列を rows から解釈できませんでした、スキップします",
                file=sys.stderr,
            )
        return None

    return total


def _money_decimal(order: dict[str, Any]) -> Decimal:
    """販売合計（税込・送料込）= current_total_price"""
    raw = order.get("current_total_price") or order.get("total_price") or "0"
    return Decimal(str(raw))


def _net_sales_decimal(order: dict[str, Any]) -> Decimal:
    """純売上高 = current_subtotal_price − current_total_tax

    日本は税込価格表示のため subtotal_price に税が含まれる。
    Shopify管理画面「純売上高」= 総売上高 − ディスカウント − 税（送料除く）
    AOV をこのベースで計算することで管理画面の「平均注文金額」と一致する。
    """
    subtotal = Decimal(str(order.get("current_subtotal_price") or order.get("subtotal_price") or "0"))
    tax = Decimal(str(order.get("current_total_tax") or order.get("total_tax") or "0"))
    return subtotal - tax


def fetch_shop_timezone_and_currency(sess: requests.Session, base: str) -> tuple[str, str]:
    r = sess.get(f"{base}/shop.json", timeout=30)
    r.raise_for_status()
    shop = r.json().get("shop") or {}
    tz = shop.get("iana_timezone") or "Asia/Tokyo"
    currency = shop.get("currency") or "JPY"
    return str(tz), str(currency)


def fetch_customer_created_map(
    sess: requests.Session,
    host: str,
    api_version: str,
    customer_ids: set[int],
) -> dict[int, datetime]:
    if not customer_ids:
        return {}
    gql_url = f"https://{host}/admin/api/{api_version}/graphql.json"
    out: dict[int, datetime] = {}
    ids_sorted = sorted(customer_ids)
    chunk_size = 50
    for i in range(0, len(ids_sorted), chunk_size):
        chunk = ids_sorted[i : i + chunk_size]
        gids = [f"gid://shopify/Customer/{cid}" for cid in chunk]
        query = """
        query($ids: [ID!]!) {
          nodes(ids: $ids) {
            ... on Customer {
              id
              createdAt
            }
          }
        }
        """
        r = sess.post(
            gql_url,
            json={"query": query, "variables": {"ids": gids}},
            timeout=60,
        )
        r.raise_for_status()
        body = r.json()
        if body.get("errors"):
            raise RuntimeError(f"GraphQL errors: {body['errors']}")
        for node in body.get("data", {}).get("nodes") or []:
            if not node or not node.get("id") or not node.get("createdAt"):
                continue
            m = re.search(r"/Customer/(\d+)$", node["id"])
            if not m:
                continue
            cid = int(m.group(1))
            created_raw = node["createdAt"]
            created = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
            out[cid] = created
    return out


def _fmt_int(n: int) -> str:
    return f"{n:,}"


def _fmt_money(amount: Decimal, currency: str) -> str:
    if currency == "JPY":
        return f"¥{int(amount):,}"
    return f"{amount} {currency}"


def _fmt_pct_one_decimal(x: float) -> str:
    return f"{x:.1f}%"


def _delta_pct_display(cur: float, prev: float) -> tuple[str, str]:
    if prev <= 0 and cur <= 0:
        return "→ 0.0% 先週比", "metric-neutral"
    if prev <= 0:
        return "▲ 100.0% 先週比", "metric-up"
    ch = (cur - prev) / prev * 100.0
    if abs(ch) < 0.05:
        return "→ 0.0% 先週比", "metric-neutral"
    if ch > 0:
        return f"▲ {abs(ch):.1f}% 先週比", "metric-up"
    return f"▼ {abs(ch):.1f}% 先週比", "metric-down"


def _delta_pt_display(cur: float, prev: float) -> tuple[str, str]:
    diff = (cur - prev) * 100.0
    if abs(diff) < 0.05:
        return "→ 0.0pt 先週比", "metric-neutral"
    if diff > 0:
        return f"▲ {abs(diff):.1f}pt 先週比", "metric-up"
    return f"▼ {abs(diff):.1f}pt 先週比", "metric-down"


def aggregate_week(
    orders: list[dict[str, Any]],
    *,
    week_start_utc: datetime,
    customer_created: dict[int, datetime],
) -> dict[str, Any]:
    total = Decimal(0)      # 販売合計（税込・送料込）→ 週次売上に使用
    subtotal = Decimal(0)   # 純売上高（税・送料除く）→ AOV に使用（Shopify管理画面と合わせる）
    n = 0
    unique_cids: set[int] = set()
    existing_cids: set[int] = set()
    for o in orders:
        total += _money_decimal(o)
        subtotal += _net_sales_decimal(o)
        n += 1
        cust = o.get("customer") or {}
        cid = cust.get("id")
        if cid is None:
            continue
        cid = int(cid)
        unique_cids.add(cid)
        c_at = customer_created.get(cid)
        if c_at is not None and c_at.astimezone(timezone.utc) < week_start_utc:
            existing_cids.add(cid)
    aov = (subtotal / n) if n else Decimal(0)
    # リピート率 = 既存顧客数 / ユニーク顧客数（Shopify管理画面の定義に合わせてユニーク顧客ベース）
    share = (len(existing_cids) / len(unique_cids)) if unique_cids else 0.0
    return {
        "order_count": n,
        "revenue": total,
        "aov": aov,
        "existing_share": share,
        "unique_customers": len(unique_cids),
    }


def build_shopify_metrics(
    cur: dict[str, Any],
    prev: dict[str, Any],
    currency: str,
    *,
    sessions_cur: int | None = None,
    sessions_prev: int | None = None,
) -> list[dict[str, str]]:
    oc_cur, oc_prev = cur["order_count"], prev["order_count"]
    rev_cur = float(cur["revenue"])
    rev_prev = float(prev["revenue"])
    aov_cur = float(cur["aov"])
    aov_prev = float(prev["aov"])
    sh_cur, sh_prev = cur["existing_share"], prev["existing_share"]

    d1, c1 = _delta_pct_display(float(oc_cur), float(oc_prev))
    d2, c2 = _delta_pct_display(rev_cur, rev_prev)
    d3, c3 = _delta_pct_display(aov_cur, aov_prev)
    d4, c4 = _delta_pt_display(sh_cur, sh_prev)

    metrics: list[dict[str, str]] = [
        {
            "label": "注文件数",
            "value": _fmt_int(int(oc_cur)),
            "delta": d1,
            "delta_class": c1,
        },
        {
            "label": "週次売上（税込）",
            "value": _fmt_money(cur["revenue"], currency),
            "delta": d2,
            "delta_class": c2,
        },
        {
            "label": "平均注文単価",
            "value": _fmt_money(cur["aov"], currency),
            "delta": d3,
            "delta_class": c3,
        },
        {
            "label": "既存顧客による注文の割合",
            "value": _fmt_pct_one_decimal(sh_cur * 100.0),
            "delta": d4,
            "delta_class": c4,
        },
    ]

    if sessions_cur is not None:
        d5, c5 = _delta_pct_display(
            float(sessions_cur),
            float(sessions_prev) if sessions_prev is not None else 0.0,
        )
        session_value = _fmt_int(sessions_cur)
        session_delta = d5
        session_delta_class = c5

        cvr_cur = oc_cur / sessions_cur * 100.0 if sessions_cur > 0 else 0.0
        cvr_prev = (
            (oc_prev / sessions_prev * 100.0 if sessions_prev and sessions_prev > 0 else 0.0)
            if sessions_prev is not None
            else 0.0
        )
        d6, c6 = _delta_pt_display(cvr_cur / 100.0, cvr_prev / 100.0)
        cvr_value = _fmt_pct_one_decimal(cvr_cur)
        cvr_delta = d6
        cvr_delta_class = c6
    else:
        session_value = "N/A"
        session_delta = "（データ取得不可）"
        session_delta_class = "metric-neutral"
        cvr_value = "N/A"
        cvr_delta = "（データ取得不可）"
        cvr_delta_class = "metric-neutral"

    metrics.append(
        {
            "label": "セッション数",
            "value": session_value,
            "delta": session_delta,
            "delta_class": session_delta_class,
        }
    )
    metrics.append(
        {
            "label": "CV率（注文/セッション）",
            "value": cvr_value,
            "delta": cvr_delta,
            "delta_class": cvr_delta_class,
        }
    )

    return metrics


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--merge-into",
        type=Path,
        help="この JSON を読み、`report.shopify` と `report.period_range` を上書きして保存",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="出力先（--merge-into 指定時は必須。未指定なら shopify 断片を stdout のみ）",
    )
    parser.add_argument(
        "--anchor-date",
        type=str,
        default="",
        help="基準日 YYYY-MM-DD（店舗タイムゾーン）。未指定なら実行日",
    )
    parser.add_argument(
        "--include-test",
        action="store_true",
        help="テスト注文を含める（既定は除外）",
    )
    parser.add_argument(
        "--paid-only",
        action="store_true",
        help="financial_status=paid の注文のみ集計",
    )
    args = parser.parse_args()

    shop_raw = os.environ.get("SHOPIFY_STORE", "").strip()
    token = os.environ.get("SHOPIFY_ACCESS_TOKEN", "").strip()
    if not shop_raw or not token:
        print("error: SHOPIFY_STORE と SHOPIFY_ACCESS_TOKEN を .env に設定してください", file=sys.stderr)
        return 1

    host = _normalize_shop_host(shop_raw)
    api_ver = os.environ.get("SHOPIFY_API_VERSION", DEFAULT_API_VERSION).strip() or DEFAULT_API_VERSION
    base = _rest_base(host, api_ver)
    sess = _session(token)

    try:
        tz_name, currency = fetch_shop_timezone_and_currency(sess, base)
    except requests.HTTPError as e:
        print(f"error: shop.json: {e}", file=sys.stderr)
        return 1

    from zoneinfo import ZoneInfo

    tz = ZoneInfo(tz_name)
    if args.anchor_date:
        anchor = date.fromisoformat(args.anchor_date)
    else:
        anchor = datetime.now(tz).date()

    report_mon = _reporting_week_monday(anchor)
    prev_mon = report_mon - timedelta(days=7)

    r_start, r_end = _week_inclusive_utc_bounds(report_mon, tz_name)
    p_start, p_end = _week_inclusive_utc_bounds(prev_mon, tz_name)

    fin = "paid" if args.paid_only else None

    try:
        cur_orders = list(
            iter_orders_created_between(sess, base, r_start, r_end, include_test=args.include_test, financial_status=fin)
        )
        prev_orders = list(
            iter_orders_created_between(sess, base, p_start, p_end, include_test=args.include_test, financial_status=fin)
        )
    except requests.HTTPError as e:
        print(f"error: orders: {e}", file=sys.stderr)
        if e.response is not None and e.response.text:
            print(e.response.text[:2000], file=sys.stderr)
        return 1

    cust_ids: set[int] = set()
    for o in cur_orders + prev_orders:
        c = o.get("customer") or {}
        if c.get("id") is not None:
            cust_ids.add(int(c["id"]))

    if not cust_ids:
        cust_created: dict[int, datetime] = {}
    else:
        try:
            cust_created = fetch_customer_created_map(sess, host, api_ver, cust_ids)
        except (requests.HTTPError, RuntimeError) as e:
            print(f"warning: 顧客 GraphQL に失敗したため既存顧客比率は 0 扱い: {e}", file=sys.stderr)
            cust_created = {}

    cur_stats = aggregate_week(cur_orders, week_start_utc=r_start, customer_created=cust_created)
    prev_stats = aggregate_week(prev_orders, week_start_utc=p_start, customer_created=cust_created)

    report_sun = report_mon + timedelta(days=6)
    prev_sun = prev_mon + timedelta(days=6)
    try:
        sessions_cur = fetch_sessions_shopifyql(sess, host, api_ver, report_mon, report_sun)
        sessions_prev = fetch_sessions_shopifyql(sess, host, api_ver, prev_mon, prev_sun)
    except Exception as e:
        print(f"warning: セッション数取得で予期しないエラー: {e}", file=sys.stderr)
        sessions_cur = None
        sessions_prev = None

    shopify_block = {
        "metrics": build_shopify_metrics(
            cur_stats,
            prev_stats,
            currency,
            sessions_cur=sessions_cur,
            sessions_prev=sessions_prev,
        ),
    }
    period_range = _format_period_jp(report_mon)

    fragment = {"shopify": shopify_block, "period_range": period_range}

    if args.merge_into:
        if not args.output:
            print("error: --merge-into には -o/--output が必要です", file=sys.stderr)
            return 1
        try:
            base_doc = json.loads(args.merge_into.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"error: merge 元 JSON: {e}", file=sys.stderr)
            return 1
        report = base_doc.get("report")
        if not isinstance(report, dict):
            print("error: merge 元に report オブジェクトがありません", file=sys.stderr)
            return 1
        report["shopify"] = shopify_block
        report["period_range"] = period_range

        # summary.sales を Shopify 実データで上書き
        # （progress_pct / footnote は月間目標に依存するためサンプル値を維持）
        rev_cur = float(cur_stats["revenue"])
        rev_prev = float(prev_stats["revenue"])
        d_rev, c_rev = _delta_pct_display(rev_cur, rev_prev)
        summary_sales = report.setdefault("summary", {}).setdefault("sales", {})
        summary_sales["value"] = _fmt_money(cur_stats["revenue"], currency)
        summary_sales["delta"] = d_rev.replace(" 先週比", "")
        summary_sales["delta_class"] = c_rev

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(base_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        print(json.dumps(fragment, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
