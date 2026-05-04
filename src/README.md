# src/

週次レポート自動化の **Python コード**を置く場所です。

## 現状

- `data/sample_report.json` — レポート1本分のベース JSON（ルートキー `report`）
- `templates/weekly_report.html.j2` — `reference/abil-weekly-report.html` 相当の Jinja2 テンプレート
- `generate_report.py` — JSON を読み HTML を書き出す
- `fetch_shopify.py` — **フェーズ2**: Admin API で注文を集計し、`report.shopify` と `report.period_range` を更新（`.env` の `SHOPIFY_*`）
- `requirements.txt` — `Jinja2` / `requests` / `python-dotenv`

### HTML のみ生成

```bash
python3 -m pip install -r src/requirements.txt
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

## GitHub Pages

リポジトリ直下の **`.github/workflows/pages.yml`** が、`main` への push のたびに `sample_report.json` から `_site/index.html` を生成して公開します。GitHub 上では **Settings → Pages → Build and deployment** の **Source** を **GitHub Actions** にしてください。既定の公開 URL は `https://<owner>.github.io/<repository>/` です。

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
