#!/usr/bin/env python3
"""週次レポート JSON から異常値・注意アラートを生成する。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

SEVERITY_RANK = {"critical": 0, "warning": 1, "notice": 2}
SEVERITY_LABEL = {"critical": "要対応", "warning": "注意", "notice": "確認"}
SEVERITY_CLASS = {
    "critical": "bg-red-100 text-red-700 border-red-200",
    "warning": "bg-yellow-100 text-yellow-700 border-yellow-200",
    "notice": "bg-blue-100 text-blue-700 border-blue-200",
}
SCORE_SUBTITLES = {
    "A": "好調です。大きな異常は検知されていません",
    "B+": "概ね良好です。一部の指標を確認してください",
    "B": "注意点があります。優先度の高い項目から確認してください",
    "C+": "改善が必要です。広告効率と売上要因を確認してください",
    "C": "改善が必要です。広告効率と売上要因を確認してください",
    "D": "要対応です。主要指標が大きく悪化しています",
}


@dataclass(frozen=True)
class Alert:
    severity: str
    channel: str
    title: str
    message: str
    evidence: str
    recommendation: str

    def to_json(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "severity_label": SEVERITY_LABEL[self.severity],
            "severity_class": SEVERITY_CLASS[self.severity],
            "channel": self.channel,
            "title": self.title,
            "message": self.message,
            "evidence": self.evidence,
            "recommendation": self.recommendation,
        }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"JSON を読み込めません: {path}: {exc}") from exc


def _money_to_float(value: Any) -> float | None:
    s = str(value or "").strip()
    if not s or s in {"—", "N/A"}:
        return None
    s = s.replace("¥", "").replace(",", "").replace("%", "").replace("×", "")
    try:
        return float(s)
    except ValueError:
        return None


def _percent_from_delta(delta: Any) -> float | None:
    s = str(delta or "")
    m = re.search(r"([▲▼])\s*([0-9]+(?:\.[0-9]+)?)%", s)
    if not m:
        return None
    sign = 1.0 if m.group(1) == "▲" else -1.0
    return sign * float(m.group(2))


def _point_from_delta(delta: Any) -> float | None:
    s = str(delta or "")
    m = re.search(r"([▲▼])\s*([0-9]+(?:\.[0-9]+)?)pt", s)
    if not m:
        return None
    sign = 1.0 if m.group(1) == "▲" else -1.0
    return sign * float(m.group(2))


def _metric_map(section: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("label", "")): item
        for item in section.get("metrics", [])
        if isinstance(item, dict)
    }


def _trend_change(values: list[Any]) -> float | None:
    if len(values) < 2:
        return None
    try:
        prev = float(values[-2])
        cur = float(values[-1])
    except (TypeError, ValueError):
        return None
    if prev <= 0:
        return None
    return (cur - prev) / prev * 100.0


def _add_sales_alerts(report: dict[str, Any], alerts: list[Alert]) -> None:
    sales = report.get("summary", {}).get("sales", {})
    sales_delta = _percent_from_delta(sales.get("delta"))
    if sales_delta is not None and sales_delta <= -10:
        alerts.append(
            Alert(
                severity="warning" if sales_delta > -20 else "critical",
                channel="Shopify",
                title="売上が先週から大きく落ちています",
                message=f"販売合計が先週比 {abs(sales_delta):.1f}% 減少しています。",
                evidence=f"販売合計: {sales.get('value', 'N/A')} / 先週比 {sales.get('delta', 'N/A')}",
                recommendation="流入減・CV率低下・平均注文単価のどこが主因かを優先して確認してください。",
            )
        )

    trend = report.get("trend_chart", {})
    sales_trend = _trend_change(trend.get("sales", []))
    if sales_trend is not None and sales_trend <= -15:
        alerts.append(
            Alert(
                severity="warning",
                channel="全体",
                title="売上トレンドが前週から急落しています",
                message=f"過去4週グラフの直近売上が前週比 {abs(sales_trend):.1f}% 減少しています。",
                evidence="売上・広告費 推移（過去4週）",
                recommendation="週次の一時要因か、広告・サイト側の継続的な悪化かを切り分けてください。",
            )
        )


def _add_mer_roas_alerts(report: dict[str, Any], alerts: list[Alert]) -> None:
    mer = report.get("summary", {}).get("mer", {})
    mer_value = _money_to_float(mer.get("value"))
    if mer_value is not None and mer_value > 30:
        alerts.append(
            Alert(
                severity="critical" if mer_value > 40 else "warning",
                channel="全体",
                title="広告費率が目標を超えています",
                message=f"売上に対する広告費率が {mer_value:.1f}% です。",
                evidence=f"MER: {mer.get('value', 'N/A')} / 目標: 30%以下",
                recommendation="ROASの低いキャンペーンを抑制し、広告費の増加が売上に連動しているか確認してください。",
            )
        )

    roas_change = _trend_change(report.get("trend_chart", {}).get("roas", []))
    if roas_change is not None and roas_change <= -15:
        alerts.append(
            Alert(
                severity="warning",
                channel="全体",
                title="全体ROASが前週から悪化しています",
                message=f"過去4週グラフの直近ROASが前週比 {abs(roas_change):.1f}% 低下しています。",
                evidence="売上・広告費 推移（過去4週）",
                recommendation="広告費を増やしたチャネルで、売上増加が追いついているか確認してください。",
            )
        )


def _add_channel_alerts(report: dict[str, Any], alerts: list[Alert], key: str, channel: str) -> None:
    metrics = _metric_map(report.get(key, {}))
    checks = [
        ("コンバージョン単価（CPA）", "CPA", "up_bad_pct", 20.0),
        ("CPC（クリック単価）", "CPC", "up_bad_pct", 20.0),
        ("ROAS", "ROAS", "down_bad_value", 0.3),
        ("CVR", "CVR", "down_bad_pt", 0.5),
    ]
    for label, short_label, kind, threshold in checks:
        metric = metrics.get(label)
        if not metric:
            continue
        delta = metric.get("delta")
        severity = "warning"
        change_text = ""
        if kind == "up_bad_pct":
            pct = _percent_from_delta(delta)
            if pct is None or pct < threshold:
                continue
            severity = "critical" if pct >= 35 else "warning"
            change_text = f"{pct:.1f}% 上昇"
        elif kind == "down_bad_value":
            raw = str(delta or "")
            m = re.search(r"▼\s*([0-9]+(?:\.[0-9]+)?)", raw)
            if not m:
                continue
            diff = float(m.group(1))
            if diff < threshold:
                continue
            severity = "critical" if diff >= 0.8 else "warning"
            change_text = f"{diff:.2f} 低下"
        else:
            pt = _point_from_delta(delta)
            if pt is None or pt > -threshold:
                continue
            severity = "critical" if pt <= -1.0 else "warning"
            change_text = f"{abs(pt):.2f}pt 低下"

        alerts.append(
            Alert(
                severity=severity,
                channel=channel,
                title=f"{channel}の{short_label}が悪化しています",
                message=f"{short_label} が先週比で {change_text}しています。",
                evidence=f"{label}: {metric.get('value', 'N/A')} / {delta or 'N/A'}",
                recommendation="対象キャンペーンの配信面・クリエイティブ・検索語句を確認し、悪化要因の大きいものから調整してください。",
            )
        )


def build_alerts(report: dict[str, Any], *, limit: int) -> list[dict[str, str]]:
    alerts: list[Alert] = []
    _add_sales_alerts(report, alerts)
    _add_mer_roas_alerts(report, alerts)
    _add_channel_alerts(report, alerts, "meta_ads", "Meta広告")
    _add_channel_alerts(report, alerts, "google_ads", "Google広告")

    unique: dict[tuple[str, str], Alert] = {}
    for alert in alerts:
        unique.setdefault((alert.channel, alert.title), alert)

    ordered = sorted(
        unique.values(),
        key=lambda a: (SEVERITY_RANK[a.severity], a.channel, a.title),
    )
    return [a.to_json() for a in ordered[:limit]]


def _grade_from_score(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B+"
    if score >= 70:
        return "B"
    if score >= 60:
        return "C+"
    if score >= 50:
        return "C"
    return "D"


def build_score(report: dict[str, Any], alerts: list[dict[str, str]]) -> dict[str, Any]:
    score = 85
    reasons: list[str] = ["初期値: 85点"]
    alert_counts = {"critical": 0, "warning": 0, "notice": 0}

    for alert in alerts:
        severity = str(alert.get("severity") or "")
        if severity in alert_counts:
            alert_counts[severity] += 1

    if alert_counts["critical"]:
        penalty = alert_counts["critical"] * 15
        score -= penalty
        reasons.append(f"要対応アラート {alert_counts['critical']}件: -{penalty}点")
    if alert_counts["warning"]:
        penalty = alert_counts["warning"] * 6
        score -= penalty
        reasons.append(f"注意アラート {alert_counts['warning']}件: -{penalty}点")

    sales_delta = _percent_from_delta(report.get("summary", {}).get("sales", {}).get("delta"))
    if sales_delta is not None:
        if sales_delta >= 10:
            score += 5
            reasons.append(f"売上先週比 +{sales_delta:.1f}%: +5点")
        elif sales_delta <= -20:
            score -= 15
            reasons.append(f"売上先週比 {sales_delta:.1f}%: -15点")
        elif sales_delta <= -10:
            score -= 8
            reasons.append(f"売上先週比 {sales_delta:.1f}%: -8点")

    mer_value = _money_to_float(report.get("summary", {}).get("mer", {}).get("value"))
    if mer_value is not None:
        if mer_value > 40:
            score -= 15
            reasons.append(f"MER {mer_value:.1f}%: -15点")
        elif mer_value > 30:
            score -= 8
            reasons.append(f"MER {mer_value:.1f}%: -8点")

    roas_change = _trend_change(report.get("trend_chart", {}).get("roas", []))
    if roas_change is not None:
        if roas_change >= 10:
            score += 4
            reasons.append(f"全体ROAS直近 +{roas_change:.1f}%: +4点")
        elif roas_change <= -15:
            score -= 8
            reasons.append(f"全体ROAS直近 {roas_change:.1f}%: -8点")

    numeric_score = max(0, min(100, round(score)))
    grade = _grade_from_score(numeric_score)
    return {
        "numeric_score": numeric_score,
        "grade": grade,
        "reasons": reasons,
        "alert_counts": alert_counts,
    }


def apply_alerts(doc: dict[str, Any], *, limit: int) -> dict[str, Any]:
    report = doc.setdefault("report", {})
    alerts = build_alerts(report, limit=limit)
    report["alerts"] = alerts
    if alerts:
        top = alerts[0]
        report["alert"] = {
            "show": True,
            "message": f"{top['channel']}：{top['message']} {top['recommendation']}",
        }
    else:
        report["alert"] = {
            "show": False,
            "message": "大きな異常は検知されていません。",
        }
    score_meta = build_score(report, alerts)
    report["overall_score"] = score_meta["grade"]
    report["score_subtitle"] = SCORE_SUBTITLES[score_meta["grade"]]
    report["score_meta"] = score_meta
    return doc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", "-b", type=Path, default=ROOT / "build" / "report_merged.json")
    parser.add_argument("--out", "-o", type=Path, default=ROOT / "build" / "report_merged.json")
    parser.add_argument("--limit", type=int, default=5, help="HTML に表示する最大アラート件数")
    args = parser.parse_args()

    if args.limit <= 0:
        print("error: --limit は1以上を指定してください", file=sys.stderr)
        return 1

    try:
        doc = _load_json(args.base)
        apply_alerts(doc, limit=args.limit)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    count = len(doc.get("report", {}).get("alerts", []))
    print(f"[Alerts] {count}件のアラートを生成: {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
