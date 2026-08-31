#!/bin/bash
# ============================================================
# validate-merge-markers.sh — 衝突マーカーが残ったまま終わらせない門番（配布物・全リポ共通）
#
# 何を止めるか:
#   ax 並走で merge 衝突が構造的に起きる。解消し忘れの行頭マーカー
#   （"<" 7 個 / ">" 7 個 + 空白）が生きた文書やコードに残ると、
#   読んだ人と AI がそのまま壊れた内容に従う。
#
# 検査対象:
#   追跡済み + 未追跡（--untracked。解消途中の未コミットファイルこそ危ない）。
#   .gitignore は効く。core.quotePath=false は日本語ファイル名対策
#   （abil-os check-stale-refs.sh で実測した誤検知の型）。
#
# 既知の限界:
#   - "=" 7 個の行（=======）は Markdown 見出し下線と衝突するため見ない。
#     行頭 "<" / ">" マーカーだけで解消し忘れは実用上捕まる
#   - 文書にマーカーを例示するときは行頭に置かないこと（インデントする）
#
# 終了コード: 0 = 残存なし / 1 = 残存あり or git grep 自体の失敗
#   （grep の失敗を「残存 0」と混同すると門番が緑のまま失効する）
# ============================================================
set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT" || exit 1
git rev-parse --git-dir >/dev/null 2>&1 || { echo "git リポジトリの外では実行できません" >&2; exit 1; }

HITS="$(git -c core.quotePath=false grep -nI --untracked -E '^(<{7}|>{7}) ' -- . 2>&1)"
RC=$?

if [ "$RC" -ge 2 ]; then
  echo "NG: git grep が失敗しました（rc=${RC}）。検査は実行されていません:" >&2
  printf '%s\n' "$HITS" >&2
  exit 1
fi

if [ "$RC" -eq 0 ] && [ -n "$HITS" ]; then
  COUNT=$(printf '%s\n' "$HITS" | grep -c .)
  echo "NG: 衝突マーカーが ${COUNT} 行残っています（マージの解消し忘れ）:"
  printf '%s\n' "$HITS" | sed 's/^/  /'
  exit 1
fi

echo "OK: 衝突マーカーの残存なし"
exit 0
