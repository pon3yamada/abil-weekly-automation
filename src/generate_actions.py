#!/usr/bin/env python3
"""OpenAI または Anthropic (Claude) API で週次レポート用の改善アクション3件を生成し、JSON の `report.actions` を上書きする。"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
DEFAULT_OPENAI_MODEL = "gpt-5.5"

_PROMPT_CORE = """あなたはEC・広告運用の分析アシスタントです。
与えられる週次レポートJSON（日本語の指標）だけを根拠に、改善アクションをちょうど3件返してください。

各アクションは次のキーをすべて含めること:
  border_color, emoji, priority, priority_bg, priority_text, channel, title, body_html
- priority は次のいずれかのみ: 緊急 / 推奨 / 中期
- priority が「緊急」なら priority_bgは bg-red-100、priority_textは text-red-600、border_colorは #EF4444 を推奨
- priority が「推奨」なら bg-yellow-100 / text-yellow-700 / #F59E0B を推奨
- priority が「中期」なら bg-blue-100 / text-brand-navy / #19448e を推奨
- channel は「Meta広告」「Google広告」「Shopify」「全体」など短い日本語
- title は1行で具体的に
- body_html はHTML断片のみ（<p>は使わず1〜3文をそのまま）。強調は <span class="font-bold text-brand-orange">...</span> を使ってよい
- scriptタグ・イベントハンドラ属性は禁止
- 数値は入力JSONにないなら捏造しない。推測する場合は「〜の可能性」などと明示
- meta_ads / google_ads 内の campaigns 配列にキャンペーン別が含まれる場合はそれも根拠に使う。trend_chart は過去数週の売上・広告費・ROASの系列がある場合のみ参照"""

_ACTION_KEYS = frozenset(
    {
        "border_color",
        "emoji",
        "priority",
        "priority_bg",
        "priority_text",
        "channel",
        "title",
        "body_html",
    }
)

_PRIORITY_DEFAULTS: dict[str, dict[str, str]] = {
    "緊急": {
        "border_color": "#EF4444",
        "emoji": "🔥",
        "priority_bg": "bg-red-100",
        "priority_text": "text-red-600",
    },
    "推奨": {
        "border_color": "#F59E0B",
        "emoji": "💡",
        "priority_bg": "bg-yellow-100",
        "priority_text": "text-yellow-700",
    },
    "中期": {
        "border_color": "#19448e",
        "emoji": "🛒",
        "priority_bg": "bg-blue-100",
        "priority_text": "text-brand-navy",
    },
}


def _sanitize_body_html(html: str) -> str:
    s = re.sub(
        r"(?is)<script\b[^>]*>.*?</script>",
        "",
        html,
    )
    s = re.sub(r"(?i)on\w+\s*=", "data-removed=", s)
    return s


def _report_context(payload: dict[str, Any]) -> dict[str, Any]:
    r = payload.get("report") or {}
    return {
        "period_range": r.get("period_range"),
        "overall_score": r.get("overall_score"),
        "score_subtitle": r.get("score_subtitle"),
        "alert": r.get("alert"),
        "summary": r.get("summary"),
        "shopify": r.get("shopify"),
        "meta_ads": r.get("meta_ads"),
        "google_ads": r.get("google_ads"),
        "compare": r.get("compare"),
        "trend_chart": r.get("trend_chart"),
    }


def _env_truthy(raw: str | None) -> bool:
    return (raw or "").strip().lower() in ("1", "true", "yes", "on")


def _extract_json_array(text: str) -> list[Any]:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s*```\s*$", "", t)
    start = t.find("[")
    end = t.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON array in model output")
    return json.loads(t[start : end + 1])


def _normalize_action(raw: dict[str, Any]) -> dict[str, str]:
    pri = str(raw.get("priority") or "推奨").strip()
    if pri not in _PRIORITY_DEFAULTS:
        pri = "推奨"
    base = dict(_PRIORITY_DEFAULTS[pri])
    out: dict[str, str] = {}
    for k in _ACTION_KEYS:
        v = raw.get(k)
        if v is not None and str(v).strip():
            out[k] = str(v).strip()
        elif k in base:
            out[k] = base[k]
        else:
            out[k] = ""
    if not out.get("title"):
        out["title"] = "（タイトルなし）"
    out["body_html"] = _sanitize_body_html(out.get("body_html") or "")
    return out


def _parse_actions_openai_json(content: str) -> list[Any]:
    obj = json.loads(content.strip())
    arr = obj.get("actions")
    if not isinstance(arr, list):
        raise ValueError('OpenAI output must be JSON object with key "actions" (array)')
    return arr


def _call_claude(
    *,
    api_key: str,
    model: str,
    context: dict[str, Any],
) -> list[dict[str, str]]:
    system = (
        _PROMPT_CORE
        + """

厳守:
- 出力は有効なJSON配列のみ（前置き・マークダウン・コードフェンスは禁止）
- 要素は3つ固定"""
    )

    user = (
        "以下のレポート要約JSONを読み、改善アクション配列のJSONだけを返してください。\n\n"
        + json.dumps(context, ensure_ascii=False, indent=2)
    )

    resp = requests.post(
        ANTHROPIC_URL,
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        json={
            "model": model,
            "max_tokens": 4096,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
        timeout=120,
    )
    if not resp.ok:
        raise RuntimeError(f"Anthropic API {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    parts = data.get("content") or []
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    arr = _extract_json_array(text)
    if not isinstance(arr, list) or len(arr) != 3:
        raise ValueError(f"expected 3 actions, got {type(arr).__name__} with len {len(arr) if isinstance(arr, list) else 'n/a'}")
    if not all(isinstance(x, dict) for x in arr):
        raise ValueError("each action must be a JSON object")
    return [_normalize_action(x) for x in arr]


def _call_openai(
    *,
    api_key: str,
    model: str,
    context: dict[str, Any],
) -> list[dict[str, str]]:
    system = (
        _PROMPT_CORE
        + """

厳守:
- 応答はJSONオブジェクト1つのみ。キー \"actions\" に上記スキーマのアクションをちょうど3個入れた配列にすること
- ほかのキーや説明文は付けない"""
    )
    user = (
        "以下のレポート要約JSONを読み、{\"actions\": [ ... 3件 ... ]} 形式のJSONだけを返してください。\n\n"
        + json.dumps(context, ensure_ascii=False, indent=2)
    )

    resp = requests.post(
        OPENAI_CHAT_URL,
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {api_key}",
        },
        json={
            "model": model,
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=120,
    )
    if not resp.ok:
        raise RuntimeError(f"OpenAI API {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        raise ValueError("OpenAI response has no choices")
    content = choices[0].get("message", {}).get("content")
    if not content or not isinstance(content, str):
        raise ValueError("OpenAI response has no message content")

    try:
        arr = _parse_actions_openai_json(content)
    except (json.JSONDecodeError, ValueError):
        arr = _extract_json_array(content)

    if not isinstance(arr, list) or len(arr) != 3:
        raise ValueError(f"expected 3 actions, got {type(arr).__name__} with len {len(arr) if isinstance(arr, list) else 'n/a'}")
    if not all(isinstance(x, dict) for x in arr):
        raise ValueError("each action must be a JSON object")
    return [_normalize_action(x) for x in arr]


def _pick_llm() -> tuple[str | None, str, str]:
    """利用する LLM を決める。戻り値は (provider, api_key, model)。provider が None ならスキップ。"""
    anth = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    oai = (os.environ.get("OPENAI_API_KEY") or "").strip()
    pref = (os.environ.get("GENERATE_ACTIONS_PROVIDER") or "").strip().lower()
    am = (os.environ.get("ANTHROPIC_MODEL") or DEFAULT_ANTHROPIC_MODEL).strip()
    om = (os.environ.get("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL).strip()

    if pref in ("anthropic", "claude"):
        if anth:
            return "anthropic", anth, am
        print(
            "notice: GENERATE_ACTIONS_PROVIDER=anthropic が指定されていますが ANTHROPIC_API_KEY がありません",
            file=sys.stderr,
        )
        return None, "", ""
    if pref in ("openai", "gpt"):
        if oai:
            return "openai", oai, om
        print(
            "notice: GENERATE_ACTIONS_PROVIDER=openai が指定されていますが OPENAI_API_KEY がありません",
            file=sys.stderr,
        )
        return None, "", ""

    if anth and not oai:
        return "anthropic", anth, am
    if oai and not anth:
        return "openai", oai, om
    if anth and oai:
        print(
            "notice: ANTHROPIC_API_KEY と OPENAI_API_KEY の両方があります。"
            "既定では OpenAI を使います。Anthropic に固定する場合は GENERATE_ACTIONS_PROVIDER=anthropic を設定してください",
            file=sys.stderr,
        )
        return "openai", oai, om
    return None, "", ""


def _try_generate_actions(
    *,
    ctx: dict[str, Any],
    provider: str,
    api_key: str,
    model: str,
    explicit_pref: bool,
) -> tuple[list[dict[str, str]] | None, str, str, Exception | None]:
    """戻り値: (actions または None, 実際に使った provider, model, 失敗時の例外)。"""
    try:
        if provider == "openai":
            return _call_openai(api_key=api_key, model=model, context=ctx), provider, model, None
        act = _call_claude(api_key=api_key, model=model, context=ctx)
        return act, provider, model, None
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError, KeyError) as e:
        oai = (os.environ.get("OPENAI_API_KEY") or "").strip()
        om = (os.environ.get("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL).strip()
        if (
            provider == "anthropic"
            and oai
            and not explicit_pref
        ):
            print(
                f"notice: Anthropic での改善アクション生成に失敗したため OpenAI にフォールバックします（初回エラー: {e}）",
                file=sys.stderr,
            )
            try:
                act = _call_openai(api_key=oai, model=om, context=ctx)
                return act, "openai", om, None
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError, KeyError) as e2:
                return None, provider, model, e2
        return None, provider, model, e


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        type=Path,
        required=True,
        help="マージ済みレポート JSON",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="出力 JSON（通常は --base と同じ）",
    )
    parser.add_argument(
        "--soft-fail",
        action="store_true",
        help="API失敗やパースエラー時、入力の actions を保ったまま出力し終了コード0",
    )
    args = parser.parse_args()

    soft_fail = args.soft_fail or _env_truthy(os.environ.get("GENERATE_ACTIONS_SOFT_FAIL"))
    provider, api_key, model = _pick_llm()

    try:
        raw = json.loads(args.base.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"error: failed to read JSON: {e}", file=sys.stderr)
        return 1

    if "report" not in raw or not isinstance(raw["report"], dict):
        print("error: JSON root must contain dict 'report'", file=sys.stderr)
        return 1

    if not provider:
        print(
            "notice: ANTHROPIC_API_KEY / OPENAI_API_KEY とも未設定、または明示プロバイダにキー不足のため actions を変更しません",
            file=sys.stderr,
        )
        raw["report"].pop("actions_meta", None)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 0

    ctx = _report_context(raw)
    pref_raw = (os.environ.get("GENERATE_ACTIONS_PROVIDER") or "").strip().lower()
    explicit_pref = pref_raw in ("anthropic", "claude", "openai", "gpt")

    actions, final_provider, final_model, gen_err = _try_generate_actions(
        ctx=ctx,
        provider=provider,
        api_key=api_key,
        model=model,
        explicit_pref=explicit_pref,
    )
    if actions is None and gen_err is not None:
        print(f"error: 改善アクション生成に失敗: {gen_err}", file=sys.stderr)
        if soft_fail:
            raw["report"].pop("actions_meta", None)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print("notice: soft-fail: wrote JSON with existing actions unchanged", file=sys.stderr)
            return 0
        return 1

    if len(actions) != 3:
        print(f"error: normalized to {len(actions)} actions, need 3", file=sys.stderr)
        if soft_fail:
            raw["report"].pop("actions_meta", None)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print("notice: soft-fail: wrote JSON with existing actions unchanged", file=sys.stderr)
            return 0
        return 1

    meta_source = "openai" if final_provider == "openai" else "anthropic"
    raw["report"]["actions"] = actions
    raw["report"]["actions_meta"] = {
        "source": meta_source,
        "model": final_model,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
