#!/bin/bash
# ============================================================
# リポ全体のリンク実在検証（配布物・全リポ共通。合否判定に AI を使わない）
#
# 検証内容:
#   リポ内すべての .md / .mdc の相対リンク（[表示名](リンク先)）について、
#   リンク先ファイル・ディレクトリが実在するか、かつ**リポジトリの中**を
#   指しているかを確かめる。
#   Web リンク（http/https）・mailto・ページ内アンカー（#）は対象外。
#
#   リポ外を指すリンク（`../../../../loop-engineering/...` 等）は、手元では
#   解決できてしまうが GitHub 上では 404 になる。実在チェックだけでは通って
#   しまうため、リポルート配下に収まっているかも見る（abil-os Issue #6 の
#   PR レビューで実際にすり抜けが見つかった）。
#
# 合否は終了コードで返す: 0 = 合格 / 1 = 不合格（問題は stderr に列挙）
# 使い方: validate-links.sh（引数なし。.claude/hooks/ に置かれる前提でルート自動判定）
# ============================================================
set -u

# このスクリプトの場所からリポジトリルートを割り出す（どこから呼んでも動くように）
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ROOT_P="$(cd "$ROOT" && pwd -P)"   # リポ外判定はシンボリックリンクを解決した実体パスで行う

ERRORS=0
FILES=0
fail() { echo "NG: $1" >&2; ERRORS=$((ERRORS + 1)); }

while IFS= read -r file; do
  FILES=$((FILES + 1))
  dir=$(dirname "$file")
  rel="${file#"$ROOT"/}"

  # [表示名](リンク先) の「リンク先」だけを列挙する
  # ★フェンスコードブロックとインラインコードを落としてから抽出する。
  #   リンク書式の再現例（`[x](foo.md)` 等）を含む文書で誤検知が発火する
  #   （2026-08-28 レビュー hinshitsu W9 で実証・badminton-ai でも実測）。
  #   検査はフェイルクローズ（Stop 差し戻し・PR 拒否）なため、誤検知は日常を止める
  while IFS= read -r target; do
    [ -z "$target" ] && continue
    case "$target" in
      http://*|https://*|mailto:*|\#*) continue ;;   # Web・アンカーは対象外（ローカルの実在だけ見る）
    esac
    path="${target%%#*}"   # ファイル内アンカー（file.md#section）はファイル部分だけ確かめる
    [ -z "$path" ] && continue
    if [ ! -e "$dir/$path" ]; then
      fail "$rel: リンク先が存在しない: $target"
      continue
    fi
    # 実在しても、リポの外を指していれば GitHub 上では 404 になる
    linkdir=$(cd "$dir/$(dirname "$path")" 2>/dev/null && pwd -P)
    if [ -z "$linkdir" ]; then
      fail "$rel: リンク先の場所を解決できない: $target"
    else
      case "$linkdir/" in
        "$ROOT_P"/*) ;;
        *) fail "$rel: リンク先がリポジトリ外を指す（GitHub 上で 404 になる）: $target" ;;
      esac
    fi
  done < <(awk '/^[[:space:]]*```/{f=!f;next} !f' "$file" 2>/dev/null \
           | sed 's/`[^`]*`//g' \
           | grep -oE '\]\([^)]+\)' | sed 's/^](//; s/)$//')

# 除外の理由:
#   node_modules/    依存の中の README を検証しても直せない（かつ巨大）
#   .claude/worktrees/  git worktree の置き場。中身は別チェックアウトの複製で二重検知になる
#   *.preview.md     原稿からの生成物（正本を検証すれば足りる）
done < <(find "$ROOT" \( -name '*.md' -o -name '*.mdc' \) -type f \
         -not -path "$ROOT/.git/*" \
         -not -path "*/node_modules/*" \
         -not -path "$ROOT/.claude/worktrees/*" \
         -not -name '*.preview.md')

[ "$FILES" -gt 0 ] || fail "検証対象の .md / .mdc が 1 つも見つからない"

if [ "$ERRORS" -gt 0 ]; then
  echo "リンク検証: 不合格（${ERRORS} 件 / ${FILES} ファイル）" >&2
  exit 1
fi

echo "リンク検証: 合格（${FILES} ファイル、相対リンクすべて実在）"
exit 0
