#!/bin/bash
# ============================================================
# Codex の門番の窓口（.codex/hooks.json の全項目がこの 1 本を呼ぶ。Issue #406）
#
#   bash .codex/hooks.sh <イベント> [<組の matcher>]   # 標準入力 = Codex のフック入力（JSON）
#
# なぜ要るか: Codex は、人が「信頼する」を押すまで .codex/hooks.json の門番を動かさない。信頼は hooks.json の
#   1 項目の**定義**（コマンドの文字列・timeout・matcher）に付き、定義を変えると外れる。外れたまま `codex exec` を
#   使うと、何も言わずに門番を飛ばす（#386 ③-3 で main に届いた）。いっぽう、呼ぶスクリプトの**中身**を変えても
#   外れない（#386 ③-2）。だから hooks.json には「この窓口を呼ぶ」ことだけを書き、どの門番を走らせるかは
#   隣の表（.codex/hooks.tsv）で決める。門番を足す・外す・timeout を変えるのは表の行で、hooks.json は動かない。
#
# 表の形（.codex/hooks.tsv。タブ区切り・# で始まる行と空行は読み飛ばす）:
#   <イベント>  <matcher>  <timeout 秒>  <スクリプトのパス（リポ直下から）>[ <引数>…]
#   - 4 列目の空白より後ろは門番への引数（空白で区切る。引用符・展開は効かない。例: .claude/hooks/guard-worktree.sh --session-start）
#   - イベント: Codex のフックのイベント名（下の EVENTS）。綴り違いは止める（黙って走らない行を作らない）
#   - matcher: * = その組・イベントで起きたときはいつも（PreToolUse では hooks.json の Bash・apply_patch の組で起きたときだけ —
#       ほかのツール（MCP など）では窓口がそもそも起きない）。それ以外は正規表現で、全体一致（^(…)$）で見る。見る値:
#       hooks.json の組に matcher があるとき（PreToolUse の Bash・apply_patch）→ 窓口の第 2 引数（＝その組の matcher の文字列）。
#         Codex がその組を起こした＝以前ならその組の門番が全部走った、なので tool_name では振り分け直さない（第 1 周 hinshitsu W1-2）
#       組に matcher が無いとき → PreToolUse・PostToolUse・PermissionRequest は入力の tool_name / SessionStart は入力の source
#       そのほかのイベント（Stop など）は * だけを書ける（見る値が無い）
#       ★SessionStart の matcher が語の | つなぎ（startup|resume など）なら、語は startup・resume・clear・compact のどれか（綴り違いを止める）
#   - timeout: その門番 1 本の上限（秒）。超えたら窓口が門番をプロセスグループごと止め（perl）、失敗（rc 142。2 ではない）として次へ進む
#     （以前の hooks.json で 1 項目が timeout したときと同じく、その門番だけが落ちて後ろは走る — 見込み。Codex の
#     timeout の扱いは未実測）。hooks.json の窓口の timeout はその組に当たる行の合計以上にしておく（ケース表 1-8 が見る）
#   - スクリプトは `bash <リポ直下>/<パス>` で、表の行の順に 1 本ずつ呼ぶ。cwd は Codex が呼んだときのまま変えない
#   - ★届かない行も止める: hooks.json に無いイベントの行・組の matcher のどれにも当たらない matcher の行（例: Write|Edit）。
#     hooks.json が読めない（jq が無い）ときはこの検査だけを飛ばす。★組の matcher は文字（Bash・apply_patch）として当てる —
#     hooks.json の組の matcher を正規表現（Bash|Shell など）にすると、その組の行は届かない行として止まる（いまは無い形。宣言した制約）
#
# 呼び方の約束:
#   - 当たる行を**全部**、表の順に走らせる（途中で exit 2 が出ても残りを走らせる — SessionStart の session-ax-signal は
#     警告で 2 を返すので、そこで打ち切ると後ろの点検が消える。以前の hooks.json は全項目を登録していた。Codex が
#     並べて走らせていたか順に走らせていたかは測っていない — #390 の実走ログでは「hook: PreToolUse」の開始の行が 2 つ続けて
#     出てから終わりの行が出ており、並べて走らせていた手がかりにはなる）
#   - どの門番にも同じ標準入力（受け取ったバイト列そのまま）を渡す。stdout・stderr は門番のものをそのまま通す
#     ★stdout は門番の順につながる。JSON を stdout に出す門番を同じイベントに 2 本並べると、JSON として読めなくなる
#     （いま JSON を出すのは stop-validate の systemMessage だけで、Stop の行はそれ 1 本。ケース表 1-10 が「JSON を出す門番は
#     1 イベントに 1 本まで」を見る — 宣言した制約）
#   - 終了コード: どれか 1 本でも 2 → 2 / 2 は無いが 0 以外がある → 最後のその値 / 全部 0 → 0。
#     2 を拒否とみなすのは Claude Code の仕様で、Codex でも 2 のとき「Blocked」と出た（#390 の実走）。2 以外の扱いは Codex では未実測
#   - ★SessionStart は 3 本が 1 項目にまとまったので、警告の 2（session-ax-signal・session-stale-local）が出ると、
#     ほかの門番の stdout（session-now の文脈）も rc 2 の返事に入る。Codex が rc 2 のとき stdout を文脈に入れるかは未実測
#   - 見る値（tool_name / source）が読めない（jq が無い・入力が JSON でない・欄が無い）ときは、matcher を見ずに
#     そのイベントの行を全部走らせる（走らせる側＝止める側に倒す。各門番は自分で tool_name を見て関係なければ通す）
#
# 止める側に倒すとき（exit 2・理由を stderr に）:
#   - イベントの引数が無い・英字だけでない / 表が無い・読めない / 行の形が壊れている（列の数・知らないイベント・
#     matcher が空か前後に空白・timeout が正の整数でない・パスが空・絶対パス・.. を含む・matcher の無いイベントに * 以外）/
#     届かない行 / 当たった行のスクリプトが無い / 当たった行の matcher が正規表現として読めない
#   - ★ただし Stop で入力の stop_hook_active が true のとき（＝止められたあとの 2 回目）は、表の壊れでは止めず理由だけ出して 0
#     （止め続けると Codex が終われない — 第 1 周 konkyo W1-4。1 回目は止めて直させる）。緩むのは窓口の表の壊れだけで、
#     表が読めれば 2 回目でも門番は走り、門番の 2 はそのまま 2（stop-validate は自分で 5 回まで差し戻す）。
#     ★表が壊れたままだと、2 回目は stop-validate が一度も走らずに終われる（宣言した穴 — 第 2 周 hinshitsu W2-2）
#   - ★Codex に窓口ごと止められた（TERM など）ときは、走っている門番が終わるまで後始末が遅れる（bash の trap は前の子を待つ）
#   - ★表に当たる行が 1 つも無いイベントは何もせず 0（門番の無いリポに同じ hooks.json を置けるようにするため — 下の「配る」）
#   - ★この窓口のファイル自体が無いときは bash が 127 で終わる。Claude Code の仕様では 2 以外は拒否にならず（素通り）、
#     Codex も同じ見込み（未実測）。窓口の外のことなので、ここでは直せない。見張り（tools/harness-alive.tsv の gate 行）が実在を見る
#
# 配る: この台本と hooks.json は全リポでバイト一致（正本は loop-engineering の templates/codex-hooks.sh と
#   templates/hooks.codex.json）。リポ固有なのは表だけ。配り方は .codex/README.md「配り方」
#
# ★bash 3.2（macOS の /bin/bash）で動くこと。連想配列・mapfile・${x,,} は使わない
# ============================================================

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TABLE="$HERE/hooks.tsv"
HJSON="$HERE/hooks.json"
EVENT="${1:-}"
GROUP="${2-}"
HAS_GROUP=0; [ "$#" -ge 2 ] && HAS_GROUP=1
EVENTS="PreToolUse PostToolUse PermissionRequest UserPromptSubmit Stop SubagentStart SubagentStop SessionStart SessionEnd PreCompact PostCompact Notification"

TMP=""
cleanup() { [ -n "$TMP" ] && rm -f "$TMP"; }
trap cleanup EXIT
trap 'cleanup; exit 143' TERM
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 129' HUP

# 受け取った標準入力をそのまま取っておく（どの門番にも同じバイト列を渡す。Stop の 2 回目の見分けにも使う）
TMP=$(mktemp "${TMPDIR:-/tmp}/codex-hooks.XXXXXX") || { echo "Codex の門番の窓口: 一時ファイルを作れない" >&2; exit 2; }
cat > "$TMP"

HAVE_JQ=0; command -v jq >/dev/null 2>&1 && HAVE_JQ=1

deny() {
  printf 'Codex の門番の窓口（.codex/hooks.sh）が止めました: %s\n' "$1" >&2
  printf '直し方: .codex/hooks.tsv（隣の表）を直す。表の形は .codex/hooks.sh の先頭のコメント。hooks.json は触らない（触ると Codex の信頼が外れる）\n' >&2
  if [ "$EVENT" = Stop ] && [ "$HAVE_JQ" = 1 ] && [ "$(jq -r 'if type == "object" then (.stop_hook_active // false) else false end' < "$TMP" 2>/dev/null)" = true ]; then
    printf '（Stop の 2 回目なので、止め続けずに終わらせます。表は直してください）\n' >&2
    exit 0
  fi
  exit 2
}

case "$EVENT" in
  ''|*[!A-Za-z]*) deny "イベントの名前が無いか、英字だけでない（受け取った引数: '${EVENT}'）" ;;
esac
[ -f "$TABLE" ] && [ -r "$TABLE" ] || deny "表 ${TABLE#"$ROOT"/} が無いか読めない"

# 表の形を全部の行で確かめる（当たらない行の壊れも、ここで止める — 壊れた行が黙って無視されないように）
ERRS=$(LC_ALL=C awk -F'\t' -v events=" $EVENTS " '
  /^[[:space:]]*#/ || /^[[:space:]]*$/ { next }
  {
    sub(/\r$/, "")
    if (NF != 4) { printf "%d 行目: 列が 4 つでない（%d 列）\n", NR, NF; next }
    if (index(events, " " $1 " ") == 0) { printf "%d 行目: 知らないイベント（%s。綴りと大文字小文字を確かめる）\n", NR, $1 }
    if ($2 == "") { printf "%d 行目: matcher が空（いつもなら *）\n", NR }
    else if ($2 ~ /^[[:space:]]|[[:space:]]$/) { printf "%d 行目: matcher の前後に空白（%s）\n", NR, $2 }
    if ($3 !~ /^[1-9][0-9]*$/) { printf "%d 行目: timeout が正の整数でない（%s）\n", NR, $3 }
    path = $4; sub(/ .*/, "", path)
    if (path == "" || path ~ /^\// || $4 ~ /(^|[\/ ])\.\.([\/ ]|$)/) { printf "%d 行目: スクリプトのパスが空・絶対パス・.. を含む（%s）\n", NR, $4 }
    if ($1 == "SessionStart" && $2 ~ /^[A-Za-z]+(\|[A-Za-z]+)*$/) { n = split($2, w, "|"); for (k = 1; k <= n; k++) if (w[k] !~ /^(startup|resume|clear|compact)$/) printf "%d 行目: SessionStart の matcher に知らない語（%s。startup・resume・clear・compact）\n", NR, w[k] }
    if ($1 !~ /^(PreToolUse|PostToolUse|PermissionRequest|SessionStart)$/ && $2 != "*") { printf "%d 行目: %s には matcher を書けない（* だけ）\n", NR, $1 }
  }' "$TABLE" 2>&1) || deny "表が読めない"
[ -z "$ERRS" ] || deny "表の形が壊れている — $(tr '\n' ' ' <<<"$ERRS")"

# 届かない行（hooks.json が窓口へ回さない行）を止める。hooks.json が読めないときは飛ばす
if [ "$HAVE_JQ" = 1 ] && [ -f "$HJSON" ] && HKINDS=$(jq -r '.hooks | to_entries[] | .key as $e | .value[] | "\($e)\u001f\(.matcher // "")"' "$HJSON" 2>/dev/null); then
  DEAD=""
  while IFS=$'\t' read -r re rm _ _; do
    [ -n "$re" ] || continue
    reach=0
    while IFS=$'\037' read -r he hm; do
      [ "$he" = "$re" ] || continue
      if [ -z "$hm" ] || [ "$rm" = "*" ]; then reach=1; break; fi
      [[ "$hm" =~ ^($rm)$ ]] && { reach=1; break; }
    done <<<"$HKINDS"
    [ "$reach" = 1 ] || DEAD="$DEAD ${re}/${rm}"
  done <<<"$(LC_ALL=C awk -F'\t' '/^[[:space:]]*#/ || /^[[:space:]]*$/ { next } { sub(/\r$/, ""); print }' "$TABLE")"
  [ -z "$DEAD" ] || deny "hooks.json が窓口へ回さない行がある（走らない門番）:${DEAD} — hooks.json の種類（イベント・組の matcher）に合わせる"
fi

# このイベントの行（matcher と timeout と パス）
ROWS=$(LC_ALL=C awk -F'\t' -v e="$EVENT" '
  /^[[:space:]]*#/ || /^[[:space:]]*$/ { next }
  { sub(/\r$/, ""); if ($1 == e) printf "%s\t%s\t%s\n", $2, $3, $4 }' "$TABLE")
[ -n "$ROWS" ] || exit 0

# 見る値（matcher の相手）
TARGET=""
if [ "$HAS_GROUP" = 1 ]; then
  TARGET=$GROUP
else
  case "$EVENT" in
    PreToolUse|PostToolUse|PermissionRequest) FIELD=tool_name ;;
    SessionStart) FIELD=source ;;
    *) FIELD="" ;;
  esac
  if [ -n "$FIELD" ] && [ "$HAVE_JQ" = 1 ]; then
    TARGET=$(jq -r --arg f "$FIELD" 'if type == "object" then (.[$f] // "") else "" end | if type == "string" then . else "" end' < "$TMP" 2>/dev/null) || TARGET=""
  fi
fi

# 当たる行を先に全部決め、スクリプトの実在を確かめてから走らせる（途中まで走って止まる、を作らない）
RUN=""
while IFS=$'\t' read -r m t p; do
  [ -n "$p" ] || continue
  if [ "$m" != "*" ] && [ -n "$TARGET" ]; then
    [[ "$TARGET" =~ ^($m)$ ]]
    mr=$?
    [ "$mr" -eq 2 ] && deny "表の matcher「${m}」が正規表現として読めない（${EVENT} の行）"
    [ "$mr" -eq 0 ] || continue
  fi
  [ -f "$ROOT/${p%% *}" ] || deny "表の門番 ${p%% *} が無い（${EVENT} の行）"
  RUN="$RUN$t	$p
"
done <<<"$ROWS"

# 1 本ずつ走らせる。timeout は perl が掛ける: 門番を新しいプロセスグループで起こし、時間が来たらグループごと TERM（1 秒後に KILL）し、
#   rc 142 で返す。グループごと止めるのは、門番の子が stdout・stderr を握ったまま残ると、呼び手が表の timeout を超えて待つため
#   （第 2 周 konkyo W2-2・hinshitsu W2-1 の実測: 1 秒の行で 8〜9 秒）。見張りの子（sleep）を立てる形は、すぐ終わる門番で
#   後始末が競合して sleep が残った（第 1 周の直しの途中の実測）のでやめた。
#   perl が無いときは上限なしで走らせる（見張れないだけ。門番は最後まで走らせる）
HAVE_PERL=0; command -v perl >/dev/null 2>&1 && HAVE_PERL=1
run_one() { # run_one <timeout> <パスと引数（空白区切り）>
  local r a
  set -f; a=($2); set +f   # 4 列目を空白で区切る（展開はしない）
  if [ "$HAVE_PERL" = 1 ]; then
    perl -e '
      my $t = shift;
      my $pid = fork;
      exit 127 unless defined $pid;
      if ($pid == 0) { setpgrp(0, 0); $SIG{ALRM} = "DEFAULT"; exec @ARGV; exit 127 }
      setpgrp($pid, $pid);
      $SIG{ALRM} = sub { kill "TERM", -$pid; sleep 1; kill "KILL", -$pid; waitpid($pid, 0); exit 142 };
      # 窓口が止められた（Codex が窓口のグループに TERM などを送った）ら、門番のグループにも回して同じ番号で終わる
      #   （門番は別のグループなので、回さないと孤児で残り timeout も掛からない — 第 3 周 hinshitsu W3-1・kensan W3-3）
      for my $sg (qw(TERM INT HUP)) { $SIG{$sg} = sub { kill $sg, -$pid; waitpid($pid, 0); exit 128 + ($sg eq "HUP" ? 1 : $sg eq "INT" ? 2 : 15) } }
      alarm $t;
      waitpid($pid, 0);
      my $s = $?;
      exit(($s & 127) ? 128 + ($s & 127) : ($s >> 8));
    ' "$1" bash "$ROOT/${a[0]}" "${a[@]:1}" < "$TMP"; r=$?
  else
    bash "$ROOT/${a[0]}" "${a[@]:1}" < "$TMP"; r=$?
  fi
  [ "$HAVE_PERL" = 1 ] && [ "$r" -eq 142 ] && printf 'Codex の門番の窓口: %s が timeout（%s 秒）を超えたので止めました（失敗として次へ進む）\n' "$2" "$1" >&2
  return "$r"
}

RC=0
while IFS=$'\t' read -r t p; do
  [ -n "$p" ] || continue
  run_one "$t" "$p"
  r=$?
  if [ "$r" -eq 2 ]; then RC=2
  elif [ "$r" -ne 0 ] && [ "$RC" -ne 2 ]; then RC=$r
  fi
done <<<"$RUN"
exit "$RC"
