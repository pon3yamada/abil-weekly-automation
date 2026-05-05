# 作業メモ（任意）

新しいチャットや数日後の自分向けに、決定事項・URL・つまずきをメモしてください。

## テンプレート

```
### YYYY-MM-DD

- やったこと:
- 次にやること:
- ブロッカー:
- メモ:
```

### 2026-05-06 — Shopify セッション数・CV率 対応 + Analytics API 調査

- **やったこと**
  - `fetch_shopify.py` に `fetch_sessions_shopifyql()` 関数を追加
    - ShopifyQL `analyticsReport` GraphQL フィールドを試みる実装
    - **結果**: Basic プランでは `analyticsReport` フィールドが GraphQL スキーマに存在しない（404 + undefinedField エラー）
    - アクセストークンの `read_analytics` スコープは正しく付与済みだが、Analytics API は管理画面のみ（API 非公開）
    - グレースフルデグレード済み：取得失敗時は警告 stderr 出力のみ・4 指標のまま継続
  - `build_shopify_metrics()` を拡張 — `sessions_cur` / `sessions_prev` 引数（キーワード only）を追加
    - セッション数が取得できた場合のみ「セッション数」「CV率（注文/セッション）」の 2 指標を metrics リストへ追記
  - `sample_report.json` にセッション数・CV率のサンプルデータを追加（サンプル値: 1,820 セッション / CV率 2.3%）
  - `fetch_shopify.py` を実行して動作確認
    - 注文件数 35件 / 売上 ¥342,440 / AOV ¥9,784 / 既存顧客比率 11.4% （直近週）
    - セッション数は警告表示のみで 4 指標レポートとして正常出力

- **Shopify Analytics API の制約まとめ**
  - `GET /admin/api/{ver}/reports.json` → 404（Basic プランでは REST Reports API 非対応）
  - `analyticsReport` GraphQL → `Field 'analyticsReport' doesn't exist on type 'QueryRoot'`（Basic プランでは非公開）
  - スコープ確認: `read_analytics` は付与済み。ただし Shopify のセッション Analytics API は**管理画面専用**で、API は Shopify Plus のみ提供
  - **回避策として検討すべき選択肢**
    1. Google Analytics 4 API（フェーズ5で実装予定）からセッション数を取得して補完
    2. Shopify Plus にアップグレードすれば `analyticsReport` が利用可能になる

- **次にやること**
  - フェーズ4: **Meta 広告 API 連携**（`fetch_meta.py` 新規作成）
    - `.env` に `META_ACCESS_TOKEN` / `META_AD_ACCOUNT_ID` を設定（未記入）
    - Marketing API v21.0 で Insights 取得: spend / purchases_value / clicks / CPC / CVR / ROAS
  - フェーズ5: **Google 広告 API 連携**（`fetch_google_ads.py` 新規作成）
    - `google-ads` ライブラリで SearchStream レポート取得
    - GA4 Reporting API でセッション数も取得 → Shopify CV率に転用
  - セッション数が取れた場合の HTML グリッドレイアウト検討（現状 6 指標で 2 行になる）

- **重要ファイル（更新）**
  - `src/fetch_shopify.py`: `fetch_sessions_shopifyql()` / `build_shopify_metrics()` 拡張済み
  - `src/data/sample_report.json`: セッション数・CV率サンプル値追加済み

### 2026-05-05 — Shopify 連携 完了 + レポートサイト構築

- **やったこと**
  - Shopify Partners に `abil-weekly-report` アプリを作成済み（260504 バージョン）
  - `shopify.app.toml` を生成し、`http://localhost:3000/callback` をリダイレクト URI に追加 → `shopify app deploy` で反映
  - `src/get_shopify_token.py` で OAuth トークン（`shpat_xxx`）を取得し `.env` の `SHOPIFY_ACCESS_TOKEN` に保存
  - `src/fetch_shopify.py` で実データ取得確認済み（注文件数・週次売上・AOV・既存顧客比率）
  - `tools.abil.shop`（GitHub Pages）をパスワード保護付きレポートサイトに改造
    - トップ: `https://tools.abil.shop/` → レポート一覧（`abil-ai` でログイン）
    - 個別: `https://tools.abil.shop/weekly_report_YYMMDD-YYMMDD/`
  - GitHub Actions `Deploy Weekly Report` ワークフロー完成・動作確認済み
    - 毎週月曜 09:00 JST に自動実行（cron）または手動実行
    - Shopify データ取得 → HTML 生成 → repo コミット → Pages デプロイ
  - GitHub Secrets 登録済み: `SHOPIFY_STORE` / `SHOPIFY_ACCESS_TOKEN` / `SHOPIFY_API_VERSION` / `REPORT_PASSWORD_HASH`

- **次にやること（新チャットで続ける）**
  - **Shopify セッション数・CV率の追加**（`fetch_shopify.py` 拡張）
    - Shopify の Analytics API または GraphQL でセッション数を取得
    - CV率 = 注文件数 ÷ セッション数 で計算
    - `sample_report.json` と `weekly_report.html.j2` に新指標を追加
  - フェーズ4: Meta 広告 API 連携
  - フェーズ5: Google 広告 API 連携

- **重要ファイル**
  - `.env`: `SHOPIFY_STORE` / `SHOPIFY_ACCESS_TOKEN` / `SHOPIFY_API_VERSION` / `SHOPIFY_CLIENT_ID` / `SHOPIFY_CLIENT_SECRET`
  - `shopify.app.toml`: Partners アプリ設定（スコープ: `read_all_orders, read_analytics, read_customers, read_orders`）
  - `src/fetch_shopify.py`: Shopify REST + GraphQL で注文集計
  - `src/generate_report.py`: JSON → 個別レポート HTML（パスワード保護付き）
  - `src/generate_index.py`: `reports_index.json` → トップページ HTML
  - `src/data/reports_index.json`: デプロイ済みレポートの一覧（Actions が自動追記）
  - `.github/workflows/pages.yml`: 週次自動化ワークフロー

- **注意事項**
  - `_site/` は `.gitignore` に含まれるが、Actions では `git add -f` で強制追加している
  - パスワード `abil-ai` のハッシュ: `10bd0d13c822595f6995db0dc2c90b9ea38f0ce5e9c90cafa56a671529a6bb08`
  - Shopify API バージョン: `2026-04`

### 2026-05-03 — Google Ads API / OAuth まわり

- **やったこと**
  - Google Cloud: OAuth 同意画面を**外部**で作成。アプリ名例: `abil-weekly-automation` 系。**テストユーザー**に OAuth ログイン用の Gmail を追加（403 access_denied 対策）。
  - **Google Auth Platform** でウェブアプリ OAuth クライアント `ABiL週次レポート - OAuth Web` を作成。承認済みリダイレクト URI に `https://developers.google.com/oauthplayground` を登録。スコープは **`https://www.googleapis.com/auth/adwords` のみ**（`cloud-platform` は付けない）。
  - [OAuth 2.0 Playground](https://developers.google.com/oauthplayground): Options → OAuth 2.0 configuration で **Use your own OAuth credentials**、**Access type: Offline**。Step 1 → Step 2 で **refresh_token** 取得。
  - プロジェクト直下に **`.env`** を作成（`.gitignore` 済み）。`GOOGLE_ADS_CLIENT_ID` / `CLIENT_SECRET` / `REFRESH_TOKEN` を記載。続けて **開発者トークン**取得後に `GOOGLE_ADS_DEVELOPER_TOKEN` を記載。
  - 開発者トークンは公式手順どおり **MCC（クライアントセンター）を新規作成**し、既存の広告アカウントを紐付けたうえで [API センター](https://ads.google.com/aw/apicenter) から申請・発行。フォームの用途は社内週次レポート・**読み取り中心**（レポート用途）で記載。
  - `GOOGLE_ADS_CUSTOMER_ID` は **ハイフンなし 10 桁**で記載（UI の `xxx-xxx-xxxx` から変換）。
- **次にやること**
  - ROADMAP **フェーズ5**: `google-ads` 等で Search/SearchStream による取得スクリプトを実装し、ローカルで 1 本確認。MCC 経由で子を触る場合は **`login-customer-id`**（MCC の CID）が必要になることがある → 必要なら `.env` に別変数で追加。
  - CI に載せるときは GitHub **Repository secrets** へ移行（値はリポジトリに含めない）。
- **ブロッカー**: なし（この時点）。
- **メモ**
  - 開発者トークン・アクセスレベルは [開発者トークン](https://developers.google.com/google-ads/api/docs/api-policy/developer-token?hl=ja) / [アクセスレベルと許容される用途](https://developers.google.com/google-ads/api/docs/api-policy/access-levels?hl=ja) を参照。上限で足りなければ基本アクセス申請を検討。
  - 秘密情報（トークン・クライアントシークレット・refresh）は **チャット・Git・スクリーンショットに載せない**。
