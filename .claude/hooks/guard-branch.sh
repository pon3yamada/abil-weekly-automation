#!/bin/bash
# ============================================================
# PreToolUse フック: main への直接コミット / push を拒否する（配布物・全リポ共通）
#
# なぜ仕組みにするか:
#   「main に直接コミットしない」をプロンプトのお願いで守らせると、長時間の
#   自律実行で確実に破られる（PHILOSOPHY §1・§6）。破られると PR 運用が崩れる。
#
# 発火モード（リポ側で選ぶ・decisions #104 のルール）:
#   既定 = 無条件（どのセッションでも main 直を拒否）。
#   本番接続あり or コラボレータありのリポは既定のまま何も置かない。
#   日常運用が main 直のリポ（山田さん専用の記録リポ等）だけ、隣に
#   guard-branch.scope という 1 行ファイル（中身: ax-only）を置く。
#   ax-only のとき、門番は AX_ISSUE が立つセッション（= ax の無人ループ）でだけ効く。
#   ★既定を厳しい方に倒す理由: scope の置き忘れは「日常の main 直が拒否される」
#     といううるさいが見える失敗になる。逆だと「本番リポの門番が黙って無効」になる（§4）。
#
# 動き:
#   - Bash ツールの git commit / git push だけを見る
#   - ブランチ削除の push（--delete / -d / :ref）は通す。main への commit / push とは
#     別物で、止めるとマージ済みブランチの後片付けが main にいるとできなくなる。
#     ただし main / master 自体の削除は止める（nagano で実測して直したバグ）
#   - main / master にいるなら 終了コード 2 で拒否。stderr が AI への指示になる
#   - 判定できないときは通す（フェイルオープン。門番が壊れて全作業が止まる方が害が大きい）
#
# 既知の限界（許容済み・2026-08-31 round2 で棚卸し）:
#   - feature ブランチから `git push origin feature:main` 型の明示 refspec はすり抜ける
#   - 人間がターミナルで直接叩く操作には効かない（AI のツール呼び出しのみ）
#   - `git -C 別リポ push` もこのリポのブランチで判定する（フックは自リポしか知らない。
#     別リポを対象にした操作が誤って止まったら、そのリポを開いたセッションでやり直す）
#   - `git -C <path> push origin --delete x` は削除例外に入れず拒否する（誤拒否側）。
#     例外の入口が `^git push` 形しか受け付けないため。削除は -C なしで実行する
#   - main / master 自体の削除を止められるのは「main / master にいるとき」だけ。
#     feature ブランチから `git push origin --delete main` は fall through して通る
#     （round2 の棚卸しで発見・裁定は worklog 2026-08-31。塞ぐには構造変更が要る）
#   - リモート名が main のとき（`git push main --delete x`）は削除例外を使わない
#     （フェイルクローズ側。コマンド全文で main を探す設計の副作用）
#
# ★リポ固有の素通し（特定リポ名を含むコマンドを通す等）をここに足さない。
#   リポ名は変わる。旧名が残った素通しは無条件バイパスの穴になる
#   （nagano の *abil-ai-ops* 素通しで実証 — 2026-08-31 の昇格で削除）。
# ============================================================

INPUT=$(cat)

# 発火モード: 隣の guard-branch.scope に ax-only とあれば ax セッション限定
SCOPE_FILE="$(dirname "$0")/guard-branch.scope"
if [ -f "$SCOPE_FILE" ] && grep -qx 'ax-only' "$SCOPE_FILE" 2>/dev/null; then
  [ -n "${AX_ISSUE:-}" ] || exit 0
fi

TOOL=$(echo "$INPUT" | jq -r '.tool_name // ""' 2>/dev/null) || exit 0
[ "$TOOL" = "Bash" ] || exit 0

CMD=$(echo "$INPUT" | jq -r '.tool_input.command // ""' 2>/dev/null) || exit 0

# git commit / git push を含まないコマンドは対象外
# （`git -C path push` 形も対象に含める — 2026-08-31 レビュー hinshitsu W1）
if ! printf '%s' "$CMD" | grep -qE 'git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+(commit|push)'; then
  exit 0
fi

# --- ブランチ削除の push は「コマンド全体が削除 push 単体のとき」だけ通す ---
# この門番の目的は「main に直接コミット / push させない」こと。
# マージ済みブランチを消す `git push origin --delete xxx` はそれに当たらないが、
# 文字列に "git push" が含まれるため巻き込まれて拒否されていた（nagano で実測）。
#
# ★例外に入れるのは「コマンド全体が削除 push 単体」のときだけ。文の区切り
#   （改行・; ・&& ・|| ・パイプ）を含むコマンドは例外に入らず、fall through して
#   main 判定で止める。行単位の grep で削除行 1 行だけを見て素通しすると、
#   同じコマンドの次の行にある `git push origin main` がそのまま通る
#   （2026-08-31 レビュー round2 hinshitsu B2-1 で 3 形とも rc=0 を実測）。
#   削除したいときは単体コマンドで実行すればよい。
#
# ★main / master 自体の削除は止める。判定はコマンド全文を 1 つの正規表現で見る
#   （裸の main|master と refs/heads/main の両形）。フラグ先行形
#   `git push --delete origin main feature/x` の main 検査が行末アンカーだけだった
#   ために素通りに退行し（round2 hinshitsu B2-2）、`refs/heads/main` 形は全形で
#   素通っていた（同 W）。検査を 1 本にまとめて両方を塞ぐ。
if ! printf '%s' "$CMD" | grep -q 'git commit'; then
  # 非空行が 2 行以上ある、または文の区切り記号を含むコマンドは例外の対象外
  NLINES=$(printf '%s\n' "$CMD" | grep -c '[^[:space:]]')
  if [ "$NLINES" -le 1 ] && ! printf '%s' "$CMD" | grep -q '[;&|]'; then
    REF='"?[A-Za-z0-9._/-]+"?'
    IS_DELETE=0
    # --delete / -d 形式（削除対象は複数可）: git push origin --delete x y
    printf '%s' "$CMD" | grep -qE "^[[:space:]]*git[[:space:]]+push[[:space:]]+(${REF}[[:space:]]+)?(--delete|-d)([[:space:]]+${REF})+[[:space:]]*$" && IS_DELETE=1
    # フラグが先に来る引数順: git push --delete origin x y
    printf '%s' "$CMD" | grep -qE "^[[:space:]]*git[[:space:]]+push[[:space:]]+(--delete|-d)[[:space:]]+${REF}([[:space:]]+${REF})+[[:space:]]*$" && IS_DELETE=1
    # コロン形式の削除: git push origin :feature/xxx
    printf '%s' "$CMD" | grep -qE "^[[:space:]]*git[[:space:]]+push[[:space:]]+${REF}([[:space:]]+:[A-Za-z0-9._/-]+)+[[:space:]]*$" && IS_DELETE=1
    if [ "$IS_DELETE" = 1 ]; then
      # main / master が引数のどこかに現れたら削除例外を使わない（fall through）。
      # 語境界は 行頭 / 空白 / コロン / 引用符 のみ — feature/main-fix や
      # feature/mainline は "/" が前に来るので一致しない（実測で確認した形）
      printf '%s' "$CMD" | grep -qE '(^|[[:space:]]|:|")(refs/heads/)?(main|master)("|[[:space:]]|$)' || exit 0
    fi
  fi
fi

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BRANCH=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null) || exit 0
[ -n "$BRANCH" ] || exit 0

if [ "$BRANCH" = "main" ] || [ "$BRANCH" = "master" ]; then
  if [ -n "${AX_ISSUE:-}" ]; then
    SWITCH_HINT="git -C \"$ROOT\" switch feature/issue-${AX_ISSUE}"
    WHY="ax の一本道は「PR 作成まで自動・マージは人間」です。main へ直接入れると
人間の判断（マージ）を飛ばすことになり、自律性の境界が崩れます。"
  else
    SWITCH_HINT="git -C \"$ROOT\" switch -c feature/作業名"
    WHY="このリポは main が本番または共同作業者に直結しています。変更は
プルリクエストで着地させ、マージは人間が判断します。"
  fi
  cat >&2 <<MSG
${BRANCH} に直接コミット / push しようとしています。拒否しました。

作業ブランチに移ってからやり直してください:

    ${SWITCH_HINT}

理由: ${WHY}
MSG
  exit 2
fi

exit 0
