#!/bin/bash
# ============================================================
# Stop フック: リンク切れが残ったまま AI を終わらせない門番（配布物・全リポ共通）
#
# 動き:
#   - AI が返事を終えようとするたびに validate-links.sh を走らせる
#   - 合格 → そのまま終了させる（日常作業を一切妨げない）
#   - 不合格 → 終了コード 2 で差し戻し、問題一覧を stderr で AI に渡す
#   - 差し戻しは 1 セッションにつき 5 回まで。超えたら諦めて人間に引き渡す
# ============================================================

INPUT=$(cat)

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REPO_NAME="$(basename "$ROOT")"

# セッションごとにやり直し回数を数える（キーは session_id。接頭辞はリポ名から導出）
SESSION=$(echo "$INPUT" | jq -r '.session_id // "unknown"')
COUNTER="${TMPDIR:-/tmp}/${REPO_NAME}-links-retry-${SESSION}"

RESULT=$(bash "$(dirname "$0")/validate-links.sh" 2>&1)
STATUS=$?

if [ "$STATUS" -eq 0 ]; then
  rm -f "$COUNTER"   # 合格したらカウンタをリセット
  exit 0
fi

COUNT=$(cat "$COUNTER" 2>/dev/null || echo 0)

if [ "$COUNT" -ge 5 ]; then
  # 上限到達: これ以上機械だけで直させず、人間に見せる
  echo "リンク検証の差し戻しが 5 回続いたため打ち切ります。残っている問題を人間が確認してください:" >&2
  echo "$RESULT" >&2
  rm -f "$COUNTER"
  exit 0
fi

echo $((COUNT + 1)) > "$COUNTER"

# 終了コード 2 = AI を止めずに差し戻す。stderr が AI への修正指示になる
{
  echo "リポ内のリンク検証に失敗しました（差し戻し $((COUNT + 1))/5 回目）。リンク切れをすべて修正してから終了してください（リンク元の修正か、リンク先の実体を置くかは文脈で判断）:"
  echo "$RESULT"
} >&2
exit 2
