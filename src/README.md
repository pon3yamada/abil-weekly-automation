# src/

週次レポート自動化の **Python コード**を置く場所です。

## 現状（フェーズ9まで完了・フェーズ7は後回し）

| ファイル | 役割 |
|---|---|
| `data/sample_report.json` | レポート1本分のベース JSON（ルートキー `report`） |
| `templates/weekly_report.html.j2` | Jinja2 テンプレート（Tailwind CSS + Chart.js） |
| `generate_report.py` | JSON を読み HTML を書き出す |
| `fetch_shopify.py` | Shopify Admin API で注文集計 → `report.shopify` / `report.summary.sales` を更新 |
| `fetch_meta.py` | Meta Marketing API でインサイト取得 → `report.meta_ads`（指標 + キャンペーン別）を更新 |
| `fetch_google_ads.py` | Google Ads REST API v20 で指標取得 → `report.google_ads`（指標 + キャンペーン別）を更新。さらに `report.summary.ad_spend` / `report.summary.mer` を実データで更新 |
| `append_to_sheets.py` | マージ済み JSON を読み、Google Sheets の「週次データ」シートに週ごと**列**として追記（A 列＝指標）。`.env` に `GOOGLE_SHEETS_*`、CI では [Secrets](../docs/NOTES.md) 参照 |
| `generate_actions.py` | **Anthropic (Claude)** または **OpenAI**（Chat Completions、`response_format: json_object`）で `report.actions` を3件生成。成功時は `report.actions_meta.source` に `anthropic` / `openai`。**両方のキーがあるときは既定で OpenAI** — Anthropic に固定したいときは `GENERATE_ACTIONS_PROVIDER=anthropic`。Anthropic が失敗し、かつ明示で Anthropic 固定でないときは OpenAI に **自動フォールバック**。`--soft-fail` / `GENERATE_ACTIONS_SOFT_FAIL` で失敗時も既存 `actions` のまま終了0 |
| `post_slack.py` | Slack Incoming Webhook に週次レポート URL と短文サマリーを投稿。`SLACK_WEBHOOK_URL` 未設定時は何もしない |
| `requirements.txt` | `Jinja2` / `requests` / `python-dotenv` / `gspread` / `google-auth` |

### フルパイプライン（ローカル確認用）

```bash
python3 -m pip install -r src/requirements.txt

# 1. Shopify データ取得
python3 src/fetch_shopify.py --merge-into build/report_with_shopify.json -o build/report_with_shopify.json

# 2. Meta 広告データ取得（.env に META_ACCESS_TOKEN / META_AD_ACCOUNT_ID が必要）
python3 src/fetch_meta.py --base build/report_with_shopify.json --out build/report_merged.json

# 3. Google 広告データ取得（.env に GOOGLE_ADS_* が必要）
python3 src/fetch_google_ads.py --base build/report_merged.json --out build/report_merged.json

# 4. Google Sheets に週次列を追記（任意・.env に GOOGLE_SHEETS_SPREADSHEET_ID と認証情報）
python3 src/append_to_sheets.py --base build/report_merged.json

# 5. LLM で改善アクションを生成（任意・`ANTHROPIC_API_KEY` または `OPENAI_API_KEY`。CI と同様にフォールバックするなら --soft-fail）
python3 src/generate_actions.py --base build/report_merged.json --out build/report_merged.json --soft-fail

# 6. HTML 生成
python3 src/generate_report.py -i build/report_merged.json -o build/report.html

# 7. Slack 通知（任意・公開 URL と .env の SLACK_WEBHOOK_URL）
# python3 src/post_slack.py --base build/report_merged.json --report-url "https://<pages>/<週スラッグ>/"
```

### HTML のみ生成（テスト用）

```bash
python3 src/generate_report.py -i src/data/sample_report.json -o build/report.html
```

### Shopify → JSON マージ → HTML

カスタムアプリの **Admin API アクセストークン**に、少なくとも `read_orders` と `read_customers`（既存顧客比率用 GraphQL）を付与してください。

```bash
python3 src/fetch_shopify.py --merge-into src/data/sample_report.json -o build/report.json
python3 src/generate_report.py -i build/report.json -o build/report.html
```

- 報告対象の週: 店舗タイムゾーンで「基準日の属する週」の**ひとつ前の週**（月〜日）。基準日は既定で実行日。`--anchor-date 2026-05-03` で固定可。
- テスト注文は既定で除外。`--include-test` で含める。支払済みのみなら `--paid-only`。

## GitHub Pages（週次デプロイ）

**`.github/workflows/pages.yml`（Deploy Weekly Report）** が、手動実行または毎週月曜 cron で次を実行します。Shopify → Meta → Google で `build/report_merged.json` を埋めたうえで **Google Sheets に列追記** → （任意）**LLM で `report.actions` を更新** → 個別レポート HTML 生成 → `reports_index.json` 更新 → `_site/` をコミット push → Pages デプロイ → （任意）**Slack に URL 通知**。改善アクション用に **`OPENAI_API_KEY` / `ANTHROPIC_API_KEY`** のほか、`OPENAI_MODEL`・`GENERATE_ACTIONS_PROVIDER`・`GENERATE_ACTIONS_SOFT_FAIL`（ワークフローでは `--soft-fail` が付与済み）を Repository secrets で渡せます。Slack は `SLACK_WEBHOOK_URL`。未設定のキーはスキップされます。

GitHub 上では **Settings → Pages → Build and deployment** の **Source** を **GitHub Actions** にしてください。カスタムドメインを使う場合は同画面で設定します。

### 独自ドメイン（例: `tools.abil.shop`）

機密性は **アクセス制御がない限り上がりません**が、ブランド用 URL としてサブドメインを使う手順です（`abil.shop` の DNS を編集できる前提）。

1. **GitHub**（このリポジトリ）→ **Settings** → **Pages** → **Custom domain** に **`tools.abil.shop`** を入力して **Save**。  
2. 同じ画面に **DNS の指示**（チェックが通るまで待つ）が出ます。典型的には **`tools` の CNAME が `<owner>.github.io` を向く**形です（プロジェクトサイトでもターゲットは **ユーザー名または組織名の `github.io`**）。  
3. **`abil.shop` の DNS を管理している画面**（Shopify 管理画面のドメイン、お名前.com など）で、その **CNAME を1本**追加する。既存の `@` やメール用レコードは変更しない。  
4. GitHub の **DNS check** が成功するまで待つ（反映に数分〜48時間かかることがある）。  
5. **Enforce HTTPS** が選べるようになったら有効にする。  
6. 公開を確認したら、Shopify Dev Dashboard の **アプリ URL** など、外部に貼る URL を **`https://tools.abil.shop/`** に差し替える。

公式: [GitHub Pages のカスタムドメイン](https://docs.github.com/ja/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site)

フェーズの進行に合わせてファイル名は変えても構いません。`../docs/ROADMAP.md` と揃えることを優先してください。
