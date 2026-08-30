# AGENTS.md — AIエージェント共通規約

ABiL.SHOP の週次レポート自動化（Shopify・広告の数値 → HTML レポート → Slack）。全AIエージェント（Claude Code / Cursor / Codex 等）はこの規約に従うこと。Claude Code は CLAUDE.md 経由でこのファイルを読み込む。

## 構成の入口

- 全体像: [README.md](README.md)、フェーズと次の一手: [docs/ROADMAP.md](docs/ROADMAP.md)、障害記録: [docs/NOTES.md](docs/NOTES.md)
- 本番は GitHub Actions の cron: `pages.yml`（週次生成 + GitHub Pages）・`notify-slack.yml`（Slack 通知）・`token_expiry_check.yml`（トークン失効の毎日監視）

## 絶対制約

- **public リポである**。API キー・トークン・顧客数値の実データ・社内固有の事情を**コミットに含めない**（Secrets は GitHub Actions の Secrets のみ。`.env` 系はリポに置かない）
- **main で直接作業しない** — 変更は作業ブランチ → Pull Request → マージは人間。main の workflow がそのまま本番 cron（「本番接続あり → 塞ぐ」）。AI セッションは `.claude/hooks/guard-branch.sh`（無条件モード）が機械で拒否する
- ワークフローの `continue-on-error: true` を安易に足さない — Google Ads API の sunset を数週間見逃した実績がある（docs/NOTES.md）。落ちるべき所は落とす
- 日時は Actions が UTC で動く前提で書く（週の計算を 3 週ずらした実績あり — docs/NOTES.md）

## 機械検証

- 土台: `bash .claude/hooks/check-goal.sh`（リンク実在・衝突マーカー・`validate-scripts.sh` = src/*.py 構文 + src/data/*.json 構文）。PR は check-goal の出力貼付が必須（guard-pr）
- 依存を要する検証（pip install 系）は土台に置かず CI（ci.yml）に任せる。ローカルに venv は無い

## メディアの扱い

- 画像・動画・資料バイナリの実体は Git に入れない（クラウドが正本、リポには台帳のみ）。既定の置き場は Google Drive
- 例外: `reference/` の完成形 HTML・`_site/` の生成物（配信の器）のみリポに置いてよい

## 言語

ドキュメント・コミットメッセージとも日本語。
