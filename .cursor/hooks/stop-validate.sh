#!/bin/bash
# ============================================================
# Stop フック（Cursor 版・汎用アダプタ）: リポが壊れたままエージェントを終わらせない門番
#
# 検証の正本は .claude/hooks/validate-*.sh（無改変で共用）。
# このファイルは Cursor の作法への変換だけを行う。
#
# ★Stop で走らせるのは汎用 2 本（validate-links / validate-merge-markers）だけ。
#   Claude 版は stop-validate-links.sh / stop-validate-merge-markers.sh の 2 本に
#   分かれていて汎用 2 本しか呼ばないのに、Cursor 版だけが validate-*.sh を全部
#   呼んでいた（配布物自体の非対称）。リポ固有の重い検査まで毎ターン走るため、
#   card-followup では Stop のたびに vitest 200 件（実測 6 秒）が回っていた
#   （2026-08-31 レビュー round1/round2 user・templates/README の設計宣言違反）。
#   リポ固有の validate-*.sh は check-goal.sh と guard-pr.sh の土台検証で走るので
#   検査の網は落ちない。落ちるのは「ターン終了時に即差し戻す」タイミングだけ。
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
for name in validate-links.sh validate-merge-markers.sh; do
  v="$HOOKS/$name"
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
