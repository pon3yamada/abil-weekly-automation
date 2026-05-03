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

リポジトリ直下の **`.github/workflows/pages.yml`** が、`main` への push のたびに `sample_report.json` から `_site/index.html` を生成して公開します。GitHub 上では **Settings → Pages → Build and deployment** の **Source** を **GitHub Actions** にしてください。公開 URL は多くの場合 `https://<owner>.github.io/<repository>/` です。

フェーズの進行に合わせてファイル名は変えても構いません。`../docs/ROADMAP.md` と揃えることを優先してください。
