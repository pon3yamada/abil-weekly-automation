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
