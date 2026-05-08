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

### 2026-05-08 — Google Sheets 週次蓄積（フェーズ6 完了）

- **やったこと**
  - `src/append_to_sheets.py` を新規作成
    - Service Account JSON（環境変数 `GOOGLE_SHEETS_CREDENTIALS`）で認証
    - `build/report_merged.json` を読み込み、以下の **23 列** を 1 行として Sheets に追記
      - 期間 / 売上 / 広告費合計 / MER
      - Shopify: 注文件数 / 売上 / AOV / 既存顧客比率
      - Meta: 広告費 / CV / CPA / クリック / CPC / CVR / ROAS
      - Google: 広告費 / CV / CPA / クリック / CPC / CVR / ROAS
      - 生成日時
    - 同一期間（`period_range`）の行が既にある場合は**上書き**、なければ末尾に**追加**
    - シート名デフォルト: `週次データ`（`GOOGLE_SHEETS_SHEET_NAME` で変更可）
    - ヘッダー行が存在しない場合は自動作成
    - `continue-on-error: true` のため、Sheets 書き込み失敗時もレポート生成を継続
  - `src/requirements.txt` に `gspread>=6.0,<7` / `google-auth>=2.20,<3` を追加
  - `.github/workflows/pages.yml` に「Google Sheets に週次データを追記」ステップを追加
    （Google 広告取得ステップの直後・週スラッグ決定ステップの直前）
  - `docs/ROADMAP.md` フェーズ6を「✅ 完了」に更新

- **GitHub Secrets に追加が必要なもの**
  - `GOOGLE_SHEETS_CREDENTIALS`: Service Account JSON をそのまま貼り付ける（改行あり可）
  - `GOOGLE_SHEETS_SPREADSHEET_ID`: 書き込み先スプレッドシートの ID
    （URL: `https://docs.google.com/spreadsheets/d/<ここ>/edit`）
  - （任意）`GOOGLE_SHEETS_SHEET_NAME`: シート名（デフォルト: `週次データ`）

- **Service Account の作り方（初回のみ）**
  1. Google Cloud Console → IAM と管理 → サービスアカウント → 「作成」
     - 名前例: `abil-weekly-sheets`
  2. キー → JSON でダウンロード
  3. Google Sheets のスプレッドシートを開き、「共有」にサービスアカウントのメールアドレスを**編集者**として追加
  4. JSON の中身を GitHub Secrets の `GOOGLE_SHEETS_CREDENTIALS` に貼り付け

- **ローカルでの動作確認方法**
  ```bash
  # .env に以下を追加
  # GOOGLE_SHEETS_CREDENTIALS_FILE=/path/to/service-account.json
  # GOOGLE_SHEETS_SPREADSHEET_ID=<スプレッドシートID>

  python3 src/append_to_sheets.py --base build/report_merged.json
  ```

- **重要ファイル（追加）**
  - `src/append_to_sheets.py`: 新規作成
  - `src/requirements.txt`: gspread / google-auth 追加
  - `.github/workflows/pages.yml`: Sheets ステップ追加

- **次にやること**
  - フェーズ7: **異常値検知**（閾値・先週比でアラート文言を実データ駆動に）
  - フェーズ8: **Claude API** で改善アクション3件を自動生成

---

### 2026-05-08 — キャンペーン別内訳・CPA・全体サマリー実数化（フェーズ5 完了）

- **やったこと**
  - **CVR 計算を修正**（Google Ads）
    - 旧: `conversions / clicks * 100`
    - 新: `conversions / (clicks + engagements) * 100`（Google 管理画面と一致）
    - GAQL に `metrics.engagements` を追加
  - **CPA（コンバージョン単価）を両チャネルに追加**
    - Google Ads: `cost / conversions`
    - Meta Ads: `spend / purchases`
    - 両チャネルのメトリクスグリッドに「コンバージョン単価（CPA）」として表示
  - **キャンペーン別内訳テーブルを追加**
    - `src/fetch_google_ads.py`: GAQL に `campaign.name` を追加。費用のあるキャンペーンを `campaigns[]` として JSON 出力（広告費降順）
    - `src/fetch_meta.py`: `/insights?level=campaign` でキャンペーン別インサイトを取得し `campaigns[]` として出力
    - `weekly_report.html.j2`: Meta / Google 各タブのメトリクスグリッド下部にキャンペーン別テーブルを表示（`campaigns[]` がある場合のみ）
    - 表示カラム: キャンペーン名 / 広告費 / CV / CPA / ROAS（Google はさらに CVR）
  - **全体サマリーを実データで更新**
    - `fetch_meta.py`: `_raw.cost` / `_raw.prev_cost` を JSON に保存
    - `fetch_google_ads.py`: `update_summary()` 関数を追加
      - Google + Meta の広告費を合算して `summary.ad_spend` を更新
      - MER（広告費 ÷ 売上）を実計算して `summary.mer` を更新
      - ステータス自動判定: ≦30% → 良好 / ≦40% → 注意 / >40% → 要改善
    - ローカル確認（2026-04-27〜05-03）:
      - 広告費合計: ¥132,502（Google ¥108,157 + Meta ¥24,345）
      - 売上: ¥342,440 → MER: 38.7%（注意）
  - `docs/ROADMAP.md` フェーズ5を「✅ 完了」に更新

- **重要ファイル（更新）**
  - `src/fetch_google_ads.py`: CVR 修正 / CPA 追加 / campaigns[] 追加 / update_summary() 追加
  - `src/fetch_meta.py`: CPA 追加 / campaigns[] 追加（/insights?level=campaign）/ _raw 追加
  - `src/templates/weekly_report.html.j2`: キャンペーン別テーブル追加（Meta・Google 両タブ）

- **次にやること**
  - フェーズ6: **Google Sheets** への週次データ蓄積（過去推移の保存）
  - フェーズ7: **異常値検知**（アラート文言を実データ駆動に）
  - フェーズ8: **Claude API** で改善アクション3件を自動生成

---

### 2026-05-08 — Google 広告 API 連携（フェーズ5）実装・CI 連携完了

- **やったこと**
  - `src/fetch_google_ads.py` を新規作成・ローカル動作確認済み
    - **gRPC ではなく REST API（requests）を使用**
      - 理由: Python 3.9 + grpcio 1.80 の互換性問題（`GRPC target method can't be resolved`）
      - `google-ads` ライブラリは不使用。`requests` で直接 REST API を呼び出す
    - **API バージョン: `v20`**（v19 は 2026年5月時点で廃止済み → 404 を返す）
    - キャンペーンレベルで集計（GAQL: `FROM campaign WHERE segments.date BETWEEN ...`）
    - 取得指標: cost / clicks / conversions / conversions_value / CPC / CVR / ROAS
    - 当週・前週を取得して先週比を算出
    - `compare` セクション（Meta vs Google の ROAS/CPC/CVR）も更新
    - グレースフルデグレード: API 失敗時は stderr 出力のみ・既存 JSON を維持
    - MCC 経由アクセスは `GOOGLE_ADS_LOGIN_CUSTOMER_ID` ヘッダーで対応
  - `.env` に認証情報を記入・保存済み
  - `docs/ROADMAP.md` のフェーズ4を「✅ 完了」に更新
  - ローカル取得結果（2026-04-27〜05-03）:
    - 当週: 広告費 ¥108,157 / クリック 1,149 / CV 19件 / ROAS 1.75×
    - 前週: 広告費 ¥102,496 / クリック 996 / CV 26件 / ROAS 2.55×

- **トラブルシューティングまとめ（次回のために）**
  - `invalid_grant`: refresh_token 失効 → OAuth 2.0 Playground で再取得（テストアプリは7日で失効）
  - `invalid_client`: Playground の Client ID 入力ミス → Google Cloud Console からコピーアイコンで再取得
  - `GRPC target method can't be resolved`: grpcio が Python 3.9 で動かない → REST API に切り替え済み
  - `404` on REST: API バージョンが廃止済み → `v20` に変更済み（v20/v21/v22 が 2026-05 時点で有効）

- **OAuth 同意画面について（重要）**
  - 現在「テスト」ステータス → **refresh_token が7日で失効する**
  - 対策: Google Cloud Console → 「OAuth 同意画面」→ **「アプリを公開」** で本番環境へ
  - 社内ツールのため審査不要で即時公開可能。公開後は refresh_token が無期限になる

- **Google Ads 設定まとめ**
  - OAuth クライアント: `ABiL週次レポート - OAuth Web`（Google Cloud）
  - 広告アカウント（子）: `GOOGLE_ADS_CUSTOMER_ID=7645332705`
  - MCC: `GOOGLE_ADS_LOGIN_CUSTOMER_ID=7453809503`
  - API バージョン: `v20`（`src/fetch_google_ads.py` の `GOOGLE_ADS_API_VERSION`）

### 2026-05-08 — Meta 広告 API 連携（フェーズ4）完了

- **やったこと**
  - Meta Business Suite でシステムユーザー `abil_weekly-automation`（Admin）を新規作成
    - ABiLAHiL（Shopify 連携アプリ）には触れず、`abil-weekly-report` アプリ専用のユーザーとして作成
    - 広告アカウント「ABiL株式会社」に全権限で割り当て
    - `abil-weekly-report` アプリに Admin 役割で追加
    - システムユーザートークンを生成（有効期限: 60日、権限: `ads_read` / `ads_management` / `pages_read_engagement`）
    - ※ `instagram_basic` / `instagram_manage_insights` はビジネスタイプアプリでは利用不可 → 将来フェーズで対応
  - `.env` に `META_ACCESS_TOKEN` / `META_AD_ACCOUNT_ID=act_862328257705590` を記入
  - `src/fetch_meta.py` を新規作成
    - Marketing API v21.0 で `/insights` を取得（spend / purchases / purchase_value / clicks / CPC / CVR / ROAS）
    - 当週・前週を取得して先週比を算出
    - `compare` セクション（Meta vs Google の ROAS/CPC/CVR）も自動更新
    - グレースフルデグレード: API 失敗時は stderr 出力のみ・既存 JSON を維持
  - ローカル動作確認済み（2026-04-27〜05-03）
    - 当週: 広告費 ¥24,345 / クリック 1,184 / CV 6件 / ROAS 1.85×
    - 前週: 広告費 ¥17,541 / クリック 277 / CV 3件 / ROAS 1.60×
  - `.github/workflows/pages.yml` に Meta ステップを追加（Shopify の直後、`continue-on-error: true`）

- **次にやること（新チャットで続ける）**
  - GitHub Secrets に以下を登録:
    - `META_ACCESS_TOKEN`: システムユーザートークン（60日で失効 → 期限前に再生成が必要）
    - `META_AD_ACCOUNT_ID`: `act_862328257705590`
  - トークン失効への対策: 60日ごとに Business Suite でトークン再生成 → Secret を更新
  - フェーズ5: **Google 広告 API 連携**（`fetch_google_ads.py` 新規作成）
    - `.env` の `GOOGLE_ADS_*` を記入して実装へ
  - 将来: Instagram 有機指標（フォロワー数・リーチ）をレポートに追加
    - 現状のアプリ設定では `instagram_basic` / `instagram_manage_insights` が利用不可
    - 別途 Facebook Login 設定またはアプリタイプ変更が必要

- **重要ファイル（更新）**
  - `.env`: `META_ACCESS_TOKEN` / `META_AD_ACCOUNT_ID` を追記
  - `src/fetch_meta.py`: 新規作成
  - `.github/workflows/pages.yml`: Meta ステップ追加済み

- **Meta 設定まとめ**
  - ビジネスアカウント: `abil_japan`（ID: 400469534495789）
  - アプリ: `abil-weekly-report`（ID: 949541937938891）
  - システムユーザー: `abil_weekly-automation`（ID: 61589193430310）
  - 広告アカウント: ABiL株式会社（ID: `act_862328257705590`）
  - トークン有効期限: 60日（2026-07-07 頃に再生成が必要）

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
  - **スコープ追加（`read_reports` / `read_customer_events`）の着手タイミング**
    → **フェーズ9（Slack Webhook）完了後**に実施する（2026-05-06 決定）

- **次にやること（新チャットで続ける）**
  - フェーズ4: **Meta 広告 API 連携**（`fetch_meta.py` 新規作成）
    - **中断ポイント**: グラフ API エクスプローラーでトークン取得途中（`ads_read` 追加 → Generate Access Token → `me/adaccounts` で ID 確認）
    - 取得したら `.env` の `META_ACCESS_TOKEN` と `META_AD_ACCOUNT_ID` を記入
    - Marketing API v21.0 で Insights 取得: spend / purchases_value / clicks / CPC / CVR / ROAS
    - **トークン取得手順（再開時）**:
      1. https://developers.facebook.com/tools/explorer/ を開く
      2. アプリ「ABiLAHiL」を選択済み
      3. 「許可を追加」→ `ads_read` / `ads_management` を追加
      4. 「Generate Access Token」をクリック → 承認
      5. URL欄を `me/adaccounts?fields=id,name` に変更 → 「送信」→ `act_XXXXXXXXXX` を確認
      6. トークンと ID を `.env` に記入して実装へ
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
