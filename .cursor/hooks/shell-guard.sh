#!/bin/bash
# ============================================================
# beforeShellExecution フック（Cursor 版・汎用アダプタ）
#
# 役割: Cursor のシェル実行前イベントを、既存の Claude Code 用 PreToolUse
# ガード（guard-branch.sh / guard-pr.sh — 無改変の正本）に中継する。
#
#   使い方（.cursor/hooks.json 側）:
#     .cursor/hooks/shell-guard.sh .claude/hooks/guard-branch.sh
#
#   変換していること:
#     入力: Cursor の {command: "..."} → Claude の {tool_name:"Bash", tool_input:{command:"..."}}
#     出力: ガードの exit 0 → {"permission":"allow"}
#           ガードの exit 2 → {"permission":"deny", "agent_message": <stderr の指示文>}
#           判定不能        → allow（フェイルオープン。ガード本体と同じ方針）
# ============================================================

GUARD_REL="$1"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
case "$GUARD_REL" in
  /*) GUARD="$GUARD_REL" ;;
  *)  GUARD="$ROOT/$GUARD_REL" ;;
esac

INPUT=$(cat)

# ガードが無い・実行できないなら通す（門番の故障で全作業を止めない）
[ -x "$GUARD" ] || { echo '{"permission":"allow"}'; exit 0; }

CMD=$(echo "$INPUT" | jq -r '.command // empty' 2>/dev/null)
[ -z "$CMD" ] && { echo '{"permission":"allow"}'; exit 0; }

# Claude PreToolUse 形の stdin に整形して、正本のガードへ渡す
CLAUDE_INPUT=$(jq -n --arg cmd "$CMD" '{tool_name: "Bash", tool_input: {command: $cmd}}')
ERR=$(printf '%s' "$CLAUDE_INPUT" | "$GUARD" 2>&1 >/dev/null)
STATUS=$?

if [ "$STATUS" -eq 2 ]; then
  jq -n --arg msg "$ERR" '{permission: "deny", agent_message: $msg}'
else
  echo '{"permission":"allow"}'
fi
exit 0
