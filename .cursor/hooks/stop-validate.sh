#!/bin/bash
# ============================================================
# Stop フック（Cursor 版・汎用アダプタ）: リポが壊れたままエージェントを終わらせない門番
#
# 検証の正本は .claude/hooks/validate-*.sh（無改変で共用・全部呼ぶ）。
# このファイルは Cursor の作法への変換だけを行う。
#
# Claude Code 版（stop-validate-*.sh）との違い:
#   - 差し戻しは exit 2 + stderr ではなく、stdout の JSON に followup_message を書く
#   - やり直し回数は stdin の loop_count（0始まり）を読むだけ。
#     打ち切りは .cursor/hooks.json の loop_limit(5) が担う
# ============================================================

INPUT=$(cat)
LOOPS=$(echo "$INPUT" | jq -r '.loop_count // 0')

HOOKS="$(cd "$(dirname "$0")/../../.claude/hooks" 2>/dev/null && pwd)"
[ -n "$HOOKS" ] || { echo '{}'; exit 0; }   # 正本が無ければ通す（フェイルオープン）

FAILS=""
for v in "$HOOKS"/validate-*.sh; do
  [ -f "$v" ] || continue
  if ! OUT=$(bash "$v" 2>&1); then
    FAILS="${FAILS}
--- $(basename "$v") ---
${OUT}"
  fi
done

if [ -z "$FAILS" ]; then
  echo '{}'
  exit 0
fi

jq -n --arg msg "機械検証に失敗しました（差し戻し $((LOOPS + 1))/5 回目）。以下をすべて修正してから終了してください:
$FAILS" '{followup_message: $msg}'
exit 0
