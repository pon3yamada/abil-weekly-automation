#!/bin/bash
# ============================================================
# Stop フック: 衝突マーカーが残ったまま AI を終わらせない門番（配布物・全リポ共通）
#
# 検証の正本は validate-merge-markers.sh（無改変で共用）。
# 動きは stop-validate-links.sh と同型:
#   - 合格 → そのまま終了（日常作業を妨げない）
#   - 不合格 → exit 2 で差し戻し、残存一覧を stderr で AI に渡す
#   - 差し戻しは 1 セッションにつき 5 回まで。超えたら人間に引き渡す
# ============================================================

INPUT=$(cat)

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REPO_NAME="$(basename "$ROOT")"

SESSION=$(echo "$INPUT" | jq -r '.session_id // "unknown"')
COUNTER="${TMPDIR:-/tmp}/${REPO_NAME}-merge-markers-retry-${SESSION}"

RESULT=$(bash "$(dirname "$0")/validate-merge-markers.sh" 2>&1)
STATUS=$?

if [ "$STATUS" -eq 0 ]; then
  rm -f "$COUNTER"
  exit 0
fi

COUNT=$(cat "$COUNTER" 2>/dev/null || echo 0)

if [ "$COUNT" -ge 5 ]; then
  echo "衝突マーカー検証の差し戻しが 5 回続いたため打ち切ります。残っている問題を人間が確認してください:" >&2
  echo "$RESULT" >&2
  rm -f "$COUNTER"
  exit 0
fi

echo $((COUNT + 1)) > "$COUNTER"

{
  echo "衝突マーカーが残っています（差し戻し $((COUNT + 1))/5 回目）。マージの解消を完了してから終了してください:"
  echo "$RESULT"
} >&2
exit 2
