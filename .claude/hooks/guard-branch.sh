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
#   - （解消: 2026-09-02）`git -C 別リポ` は判定の対象外にした。詳細は本文の A 節
#   - main / master 自体の削除を止められるのは「main / master にいるとき」だけ。
#     feature ブランチから `git push origin --delete main` は fall through して通る
#     （round2 の棚卸しで発見・裁定は worklog 2026-08-31。塞ぐには構造変更が要る）
#   - リモート名が main のとき（`git push main --delete x`）は削除例外を使わない
#     （フェイルクローズ側。コマンド全文で main を探す設計の副作用）
#   - （解消: 2026-09-02）実行されない文字列としての `git push` は対象外にした。詳細は本文の B 節。
#     ただし**引用符の中に文の区切り記号を含む**文字列は今も拒否する
#     （`echo "手順: a; git push origin main"`）。区切りで割ると git 始まりの文が現れるため。
#     引用の解釈まで踏み込むと素通しの穴になるので、ここは拒否側に倒したまま
#   - 同型で、**ヒアドキュメントの本文**に書いた `git push origin main` も拒否する
#     （`cat > 手順.md <<EOF` … `EOF`）。手順書を heredoc で書く作業は今も止まる。
#     heredoc の終端（引用付き終端・`<<-`・複数 heredoc）まで解釈すると誤りやすいので未対応。
#     回避策: 手順書は Write ツールか、行頭を字下げして書く
#   - `git -C <存在しないパス>` は「別リポか判定できない」ので従来どおり判定を続ける
#     （拒否側。存在しないパスへの push はどのみち失敗するので実害は小さい）
#   - `=` を含むオプション付きの削除（`--force-with-lease=x:abc`）・非 ASCII の
#     ブランチ名の削除は例外に入らず拒否する（REF の字種を絞っているため）
#   - **削除しか含まないコマンドでも、複数行なら拒否する**（`git fetch` 改行
#     `git push origin --delete x`）。混在 push を塞いだ代償。削除は 1 行で実行する
#   - パイプを含む削除（`... --delete x | cat`）も同様に拒否する
#
# ★これらの限界は tools/guard-branch-cases.sh の「6. 既知の限界」節に**ケースとして
#   固定**してある（loop-engineering）。挙動を変えたらケース表も同時に直すこと。
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
# ★-C の繰り返しは ? ではなく * で受ける。? だと `git -C a -C b push origin main` が
#   この粗いフィルタに一致せず、門番に届く前に素通りしていた（元からの穴。
#   2026-09-02 に A のケース表 8 節を書いていて発見）。git は -C を累積で解釈する。
if ! printf '%s' "$CMD" | grep -qE 'git([[:space:]]+-C[[:space:]]+[^[:space:]]+)*[[:space:]]+(commit|push)'; then
  exit 0
fi

# --- B. 実行されない文字列としての git は対象外（2026-09-02 追加）---------------
# 以前は「コマンド全文に git commit / push という並びがあるか」だけを見ていたため、
# `echo "git push origin main"` や `rg -n 'git push' docs/` のような**実行されない
# 文字列**にも発火し、手順を文書に書く作業が門番に止まっていた（利用者の申告で発覚）。
#
# 判定を「文の先頭が git か」で足切りする。文の区切りは 改行 / ; / && / || / パイプ。
# 先頭の環境変数代入（VAR=val）と開き括弧は読み飛ばす（`AX_ISSUE=1 git push` を拾うため）。
#
# ★この節は**従来の条件との AND** であって、新たに拒否するケースを一つも増やさない。
#   「上の grep が拾った」かつ「git 始まりの文がある」ときだけ先へ進む。緩める変更を
#   足すときは、この AND の形を崩さないこと（崩すと素通しではなく誤拒否が増える）。
STMTS=$(printf '%s' "$CMD" | sed -e 's/&&/;/g' -e 's/||/;/g' | tr ';|' '\n\n')
HAS_GIT_STMT=0
while IFS= read -r stmt; do
  # 先頭の空白・開き括弧・環境変数代入を落としてから先頭語を見る
  s=$(printf '%s' "$stmt" | sed -E 's/^[[:space:](]*//; s/^([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+)*//')
  case "$s" in
    git|git[[:space:]]*) HAS_GIT_STMT=1; break ;;
  esac
done <<STMTS_EOF
$STMTS
STMTS_EOF
[ "$HAS_GIT_STMT" = 1 ] || exit 0

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# --- A. 別リポを対象にした git は判定しない（2026-09-02 追加）------------------
# 以前は `git -C <他リポ> push` を**このリポのブランチ**で判定していた。main にいる
# リポ（例: abil-os）を開いていると、他リポ宛の commit / push が一律で拒否される。
#
# ★これは守りを緩める変更ではない。フックは**開いたリポの設定しか読まない**
#   （AGENTS.md「フックは Claude Code を開いたリポの設定しか読まない」2026-08-25 実測）。
#   つまり他リポの main は元から一切守れておらず、誤拒否だけをしていた。守れない範囲で
#   人を止めるのをやめる、という整理。他リポの main を守りたいならそのリポで開き直す。
#
# 同一リポの別 worktree は「別リポ」に**しない**。--git-common-dir は worktree 間で
# 同じ値を返すので、これで親子を同一視できる（abil-os と abil-os--issue-42 で実測）。
# toplevel で比べると worktree が別リポ扱いになり、`git -C ../abil-os push` で
# 親の main へ push できてしまう。
#
# 判定できないとき（パスが存在しない・-C が複数ある・git リポでない）は**従来どおり
# 判定を続ける**（フェイルクローズ側。ここだけは素通しに倒さない）。
# ★個数は grep -o | wc -l で数える。grep -c は「一致した**行数**」なので、
#   1 行に -C が 2 つあっても 1 と数えてしまう（`git -C 他リポ -C 自リポ push` が
#   素通しになる。ケース表 8 節で検出した実バグ — 2026-09-02）。
NCFLAG=$(printf '%s' "$CMD" | grep -oE '(^|[[:space:]])-C[[:space:]]+[^[:space:]]+' | grep -c . )
if [ "$NCFLAG" = 1 ]; then
  TPATH=$(printf '%s' "$CMD" | grep -oE '(^|[[:space:]])-C[[:space:]]+[^[:space:]]+' | head -1           | sed -E 's/.*-C[[:space:]]+//' | tr -d "\"'")
  case "$TPATH" in "~") TPATH="$HOME" ;; "~/"*) TPATH="$HOME/${TPATH#\~/}" ;; esac
  CWD=$(echo "$INPUT" | jq -r '.cwd // ""' 2>/dev/null)
  [ -n "$CWD" ] || CWD="$ROOT"
  case "$TPATH" in /*) ABS="$TPATH" ;; *) ABS="$CWD/$TPATH" ;; esac
  OTHER=$(git -C "$ABS" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
  SELF=$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
  if [ -n "$OTHER" ] && [ -n "$SELF" ] && [ "$OTHER" != "$SELF" ]; then
    exit 0
  fi
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
      # feature/mainline は "/" が前に来るので一致しない（実測で確認した形）。
      # 接頭辞は refs/heads/ と heads/ の両方を見る。git は `--delete heads/main` を
      # refs/heads/main に展開して main を消すため（round3 hinshitsu W2 — 実 bare リポ
      # への push で展開を目撃。新旧とも素通りしていた元からの穴）
      printf '%s' "$CMD" | grep -qE '(^|[[:space:]]|:|")((refs/)?heads/)?(main|master)("|[[:space:]]|$)' || exit 0
    fi
  fi
fi

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
