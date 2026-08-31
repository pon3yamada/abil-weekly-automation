#!/bin/bash
# ============================================================
# PreToolUse フック: 中身の薄いプルリクエストを作らせない門番（配布物・全リポ共通）
#
# PR は人間がマージを判断する唯一の場所（認知がボトルネック）。
#   - 本文は --body-file 必須（後から機械検証・保管できる形にする）
#   - pr-body の必須節が揃っているか機械で確認（型: loop-engineering/templates/pr-body.md）
#   - check-goal.sh の出力がそのまま貼られているか（自己申告ではなく計測の証拠）
#   - 土台検証（validate-*.sh 全部）が落ちている状態では PR を作らせない
#   - 判定できないときは通す（フェイルオープン）
#
# リポ固有の検査（台帳ゲート・self-test 等）を足すときはこのファイルに追記してよい
# （harness.tsv では skeleton 宣言 = リポ固有の進化を許す部品。abil-os の
#   検査 5・6 が先例）。ただし共通部 0〜4 は崩さないこと。
# 移植元: nagano-tosou-site → abil-os（ガード 3 層の系譜）
# ============================================================

INPUT=$(cat)

TOOL=$(echo "$INPUT" | jq -r '.tool_name // ""' 2>/dev/null) || exit 0
[ "$TOOL" = "Bash" ] || exit 0

CMD=$(echo "$INPUT" | jq -r '.tool_input.command // ""' 2>/dev/null) || exit 0

case "$CMD" in
  *"gh pr create"*) MODE=create ;;
  *"gh pr merge"*)  MODE=merge ;;
  *) exit 0 ;;
esac

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HOOKS="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 0

# --- 0. 共通ガード: 衝突マーカーと origin/main への追随 ---

# 衝突マーカーが残ったまま PR を作らせない・マージさせない
if [ -f "$HOOKS/validate-merge-markers.sh" ]; then
  if ! MOUT=$(bash "$HOOKS/validate-merge-markers.sh" 2>&1); then
    { echo "PR の${MODE}を拒否しました。衝突マーカーが残っています:"
      echo "$MOUT"; } >&2
    exit 2
  fi
fi

# 対象ブランチが origin/main に追随しているか。
#   create: いまの HEAD が対象
#   merge:  PR のヘッドブランチが対象（gh pr merge <番号> の番号から引く。
#           番号なしなら現在ブランチ）。GitHub の mergeStateStatus は
#           branch protection なしだと behind でも CLEAN を返すため自前で見る
# 判定材料が揃わないときは通す（フェイルオープン）
git fetch origin -q 2>/dev/null || true
TARGET=""
if [ "$MODE" = "create" ]; then
  TARGET="HEAD"
else
  # 番号はフラグの後に来ることもある（gh pr merge --squash 28）ので、
  # "gh pr merge" 以降の最初の独立した数字を対象とみなす
  PRNUM=$(echo "$CMD" | sed -E 's/.*gh pr merge//' | grep -oE '(^| )[0-9]+' | head -1 | tr -d ' ')
  if [ -n "$PRNUM" ]; then
    HEADREF=$(gh pr view "$PRNUM" --json headRefName -q .headRefName 2>/dev/null)
    [ -n "$HEADREF" ] && git rev-parse -q --verify "origin/$HEADREF" >/dev/null 2>&1 \
      && TARGET="origin/$HEADREF"
  else
    TARGET="HEAD"
  fi
fi
if [ -n "$TARGET" ] && git rev-parse -q --verify origin/main >/dev/null 2>&1; then
  if ! git merge-base --is-ancestor origin/main "$TARGET" 2>/dev/null; then
    { echo "PR の${MODE}を拒否しました。対象ブランチ（$TARGET）が origin/main に追随していません。"
      echo "並走中の他ブランチのマージが先に入っています。origin/main を取り込み、"
      echo "検査を通してからやり直してください。"; } >&2
    exit 2
  fi
fi

[ "$MODE" = "merge" ] && exit 0

# --- 以降は gh pr create のみ ---

# --- 1. 本文はファイルで渡させる ---
BODY_FILE=$(echo "$CMD" | grep -oE -- '--body-file[= ]+[^ ]+' | head -1 | sed 's/--body-file[= ]*//')
if [ -z "$BODY_FILE" ]; then
  cat >&2 <<'MSG'
PR の本文は --body-file でファイルとして渡してください（--body の直書きは拒否します）。

    gh pr create --title "..." --body-file /path/to/pr-body.md

本文の型: ~/ai-workbench/work/loop-engineering/templates/pr-body.md
必須節: 作ったもの / ゴールの計測結果（check-goal.sh の出力をそのまま貼る）/ 動作確認 /
        情報源の食い違い / 確認してほしい判断 / 未解決の論点（無い節は「なし」と書く）
MSG
  exit 2
fi
case "$BODY_FILE" in /*) ;; *) BODY_FILE="$ROOT/$BODY_FILE" ;; esac
[ -f "$BODY_FILE" ] || { echo "PR 本文のファイルが見つかりません: $BODY_FILE" >&2; exit 2; }

BODY=$(cat "$BODY_FILE")
MISSING=""

# --- 2. 必須節（型: templates/pr-body.md。無い内容は「なし」と書けばよい）---
for sec in "## 作ったもの" "## ゴールの計測結果" "## 動作確認" "## 情報源の食い違い" "## 確認してほしい判断" "## 未解決の論点"; do
  case "$BODY" in
    *"$sec"*) ;;
    *) MISSING="${MISSING}
  - 節「${sec}」が無い" ;;
  esac
done

# --- 3. check-goal.sh の出力がそのまま貼られているか（出力に必ず含まれる見出しで判定）---
case "$BODY" in
  *"=== 機械検証（土台） ==="*) ;;
  *) MISSING="${MISSING}
  - check-goal.sh の出力がそのまま貼られていない（「=== 機械検証（土台） ===」を含む出力を貼る）" ;;
esac

# --- 4. 土台検証が落ちたまま PR を出させない（validate-*.sh を全部呼ぶ）---
for v in "$HOOKS"/validate-*.sh; do
  [ -f "$v" ] || continue
  vname=$(basename "$v")
  if ! VALIDATE_OUT=$(bash "$v" 2>&1); then
    MISSING="${MISSING}
  - ${vname} が不合格。直してから PR を作ること:
$(echo "$VALIDATE_OUT" | sed 's/^/      /')"
  fi
done

if [ -n "$MISSING" ]; then
  {
    echo "PR の作成を拒否しました。以下を満たしてからやり直してください:"
    echo "$MISSING"
    echo
    echo "雛形: ~/ai-workbench/work/loop-engineering/templates/pr-body.md"
  } >&2
  exit 2
fi

exit 0
