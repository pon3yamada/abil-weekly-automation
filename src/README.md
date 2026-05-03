# src/

週次レポート自動化の **Python コード**を置く場所です。

## 現状（フェーズ1の骨格）

- `data/sample_report.json` — レポート1本分のダミーデータ（ルートキー `report`）
- `templates/weekly_report.html.j2` — `reference/abil-weekly-report.html` 相当の Jinja2 テンプレート
- `generate_report.py` — JSON を読み HTML を書き出す
- `requirements.txt` — 現状は `Jinja2` のみ

```bash
python3 -m pip install -r src/requirements.txt
python3 src/generate_report.py -i src/data/sample_report.json -o build/report.html
```

## これから置く想定のもの

- `fetch_shopify.py` — Shopify から指標取得（分割してもよい）

フェーズの進行に合わせて、上記は名前を変えても構いません。`../docs/ROADMAP.md` と揃えることを優先してください。
