#!/bin/bash
# ============================================================
# ゴール計測（2 層）— ループの「どうなったら終わりか」を数える（配布物・全リポ共通）
#
# 1 層目（土台）: リポが壊れていないか。★同じディレクトリの validate-*.sh を
#   **全部自動で呼ぶ**。リポ固有の検査を足したいときは validate-<名前>.sh を
#   1 本置くだけでよく、このファイル自体は全リポでバイト一致のまま保てる
#   （= harness.tsv で exact 宣言でき、ドリフト検知が効き続ける）。
#   ★重い検査（ビルド・分オーダーのテスト）は validate-*.sh に置かないこと。
#     Stop フックが同じ土台を毎回呼ぶ設計のリポでは 1 周ごとに待ちが入る。
#     ビルドは Issue 層の goals/issue-N.sh か PR ゲートに置く。
# 2 層目（Issue）: ax 実行中（AX_ISSUE あり）は、その Issue 専用の
#   合格ライン .claude/hooks/goals/issue-<番号>.sh を要求する。
#   ★ファイルが無ければ不合格。「ゴール検査を書かない限り絶対に
#   緑にならない」形（nagano-tosou-site の check-goal と同型）。
#
# 合格ラインは ax の AI が実装前に書き、赤を目撃してからコードに
# 触ること（loop-engineering decisions #46）。
#
# 終了コード: 0 = ゴール到達 / 1 = 未達
# ============================================================
set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HOOKS="$(cd "$(dirname "$0")" && pwd)"

echo "=== 機械検証（土台） ==="
VALIDATE_OK=1
FOUND=0
for v in "$HOOKS"/validate-*.sh; do
  [ -f "$v" ] || continue
  FOUND=$((FOUND + 1))
  name=$(basename "$v")
  if OUT=$(bash "$v" 2>&1); then
    echo "  [x] ${name}: 合格"
  else
    echo "  [ ] ${name}: 不合格"; echo "$OUT" | sed 's/^/      /'; VALIDATE_OK=0
  fi
done
# 検査が 1 本も無い = 「検証していない場所を緑と読む」（§4）。土台ゼロは不合格
if [ "$FOUND" -eq 0 ]; then
  echo "  [ ] validate-*.sh が 1 本も無い（土台の検査ゼロは合格ではない）"
  VALIDATE_OK=0
fi

# origin/main への追随（ax 実行中のみ。並走で「古い main から分岐したまま
# PR が CLEAN に見える」を機械で赤くする — abil-os Issue #36 の実測）
if [ -n "${AX_ISSUE:-}" ]; then
  cd "$ROOT" || exit 1
  if ! git fetch origin main -q 2>/dev/null; then
    echo "  [!] git fetch 失敗（オフライン？）。追随判定は最後に取得した origin/main で行う"
  fi
  if git rev-parse -q --verify origin/main >/dev/null 2>&1; then
    if git merge-base --is-ancestor origin/main HEAD 2>/dev/null; then
      echo "  [x] origin/main に追随済み"
    else
      echo "  [ ] origin/main 未追随。origin/main を取り込み、検査を通してから続けること"
      VALIDATE_OK=0
    fi
  else
    echo "  [!] origin/main が見つからないため追随判定をスキップ"
  fi
fi

# ------------------------------------------------------------
# 2 層目: ax 実行中はその Issue の合格ラインを要求する
# ------------------------------------------------------------
ISSUE_OK=1
if [ -n "${AX_ISSUE:-}" ]; then
  echo
  echo "=== Issue #${AX_ISSUE} の合格ライン ==="
  GOAL_SCRIPT="$ROOT/.claude/hooks/goals/issue-${AX_ISSUE}.sh"
  if [ ! -f "$GOAL_SCRIPT" ]; then
    echo "  [ ] .claude/hooks/goals/issue-${AX_ISSUE}.sh が無い"
    echo "      この Issue の「成功の定義」を終了コードで判定するスクリプトを先に書くこと。"
    echo "      実装より前に書き、赤を目撃してからコードに触る（decisions #46）。"
    ISSUE_OK=0
  # 空・コメントだけのファイルは拒否（0 バイトを置くだけで緑になる抜け道を塞ぐ）
  elif [ ! -s "$GOAL_SCRIPT" ] || [ "$(grep -vcE '^[[:space:]]*(#|$)' "$GOAL_SCRIPT")" -lt 1 ]; then
    echo "  [ ] goals/issue-${AX_ISSUE}.sh が空、またはコメントだけで中身がない"
    echo "      「成功の定義」の各項目を、終了コードで判定する検査に翻訳すること。"
    ISSUE_OK=0
  elif ISSUE_OUT=$(bash "$GOAL_SCRIPT" 2>&1); then
    printf '%s\n' "$ISSUE_OUT"
    echo "  [x] Issue #${AX_ISSUE} の合格ラインに到達"
  else
    printf '%s\n' "$ISSUE_OUT"
    echo "  [ ] Issue #${AX_ISSUE} の合格ラインに未到達"
    ISSUE_OK=0
  fi
fi

echo
if [ "$VALIDATE_OK" -eq 1 ] && [ "$ISSUE_OK" -eq 1 ]; then
  echo "ゴール到達: ✅ 機械検証 合格${AX_ISSUE:+ + Issue #${AX_ISSUE} の合格ライン}"
  exit 0
fi
echo "ゴール未達: 検証 $([ "$VALIDATE_OK" -eq 1 ] && echo 合格 || echo 不合格)${AX_ISSUE:+ / Issue #${AX_ISSUE} $([ "$ISSUE_OK" -eq 1 ] && echo OK || echo 未達)}"
exit 1
