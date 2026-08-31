#!/bin/bash
# ============================================================
# validate-scripts.sh — スクリプトが構文的に壊れたまま終わらせない門番（このリポ固有）
#
# なぜこの範囲か:
#   このリポの本番は GitHub Actions の cron（週次レポート生成 + Slack 通知）。
#   ローカルには venv が無く依存も入っていないため、pip install を要する検証は
#   土台に載せられない（毎周ネットワークを叩くことになる）。依存ゼロで守れるのは
#   「構文が壊れたまま push して週次が丸ごと落ちる」で、それだけを見る:
#     1. src/*.py 全本の構文（ast.parse — CI の py_compile と同じ意図。
#        .pyc を書かないので フックに向く）
#     2. src/data/*.json の構文（sample_report.json が壊れると生成が全滅）
#   トークン失効・API バージョン等の実行時故障は token_expiry_check.yml（毎日）
#   と実行ログの守備範囲で、ここでは原理的に捕まらない。
#
# 依存: python3 のみ。合否は終了コード: 0 = 合格 / 1 = 不合格
# ============================================================
set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ERRORS=0
PY_N=0
JSON_N=0
fail() { echo "NG: $1" >&2; ERRORS=$((ERRORS + 1)); }

while IFS= read -r f; do
  PY_N=$((PY_N + 1))
  if ! ERR=$(python3 -B -c "import ast,sys; ast.parse(open(sys.argv[1],encoding='utf-8').read(), sys.argv[1])" "$f" 2>&1); then
    fail "${f#"$ROOT"/}: Python 構文が壊れている: $(echo "$ERR" | tail -1)"
  fi
done < <(find "$ROOT/src" -name '*.py' -type f 2>/dev/null)

while IFS= read -r f; do
  JSON_N=$((JSON_N + 1))
  if ! ERR=$(python3 -c "import json,sys; json.load(open(sys.argv[1],encoding='utf-8-sig'))" "$f" 2>&1); then
    fail "${f#"$ROOT"/}: JSON が壊れている: $(echo "$ERR" | tail -1)"
  fi
done < <(find "$ROOT/src/data" -name '*.json' -type f 2>/dev/null)

[ "$PY_N" -gt 0 ] || fail "検証対象の src/*.py が 1 つも見つからない（構成が変わった？）"

if [ "$ERRORS" -gt 0 ]; then
  echo "スクリプト検証: 不合格（${ERRORS} 件 / py ${PY_N} 本・json ${JSON_N} 本）" >&2
  exit 1
fi

echo "スクリプト検証: 合格（py ${PY_N} 本・json ${JSON_N} 本）"
exit 0
