# マイルストーンと優先順位（提案）

「まだ決めていない」場合の**おすすめ順**です。途中で順番を入れ替えて問題ありません。

## なにを優先するか（設計の考え方）

- **先に「データの形」を1か所に固定する**と、HTML・Slack・グラフの数値ズレを防げる（レビューでも指摘された「SSoT」）。
- **APIは難易度の低い順**：Shopify（APIキー）→ Meta → Google（審査あり）。
- **GitHub Actions は「中身が動いてから」**でもよい。空の cron より、ローカルで1本取れた方がデバッグしやすい。

---

## フェーズ一覧

| フェーズ | 内容 | 状態 | 完了の目安 |
|---------|------|------|------------|
| **0** | プロジェクト場所・ドキュメント（このフォルダ） | ✅ 完了 | — |
| **1** | **レポート用 JSON（1ファイル）**を正とし、それから **HTML を生成**する骨格（ダミーデータでOK） | ✅ 完了 | テンプレートと生成スクリプトが `src/` にあり、毎回同じ構造のHTMLが出る |
| **2** | **Shopify** からローカルで数値取得 → JSON にマージ | ✅ 完了 | ターミナルまたはファイルで先週分が取れる |
| **3** | **GitHub Actions**（`workflow_dispatch` または週次 cron）で `src` を実行。Secrets に API キーを登録 | ✅ 完了 | 手動または定期でジョブが緑になる |
| **4** | **Meta 広告 API** を追加 | ✅ 完了 | JSON に Meta 指標が入る |
| **5** | **Google 広告 API** を追加（審査完了後） | ✅ 完了 | JSON に Google 指標が入る |
| **6** | **Google Sheets** へ生データ追記（蓄積） | ✅ 完了 | A 列に指標・横軸に週の列が増える |
| **7** | **異常値検知**（閾値・先週比）とレポート内アラート | 🔲 後回し | アラート文言がデータ駆動。**次の候補**: フェーズ10（データ実装）との前後は運用優先で決める |
| **8** | **LLM（Claude または OpenAI）** で改善アクション3件を生成し JSON/HTML に反映 | ✅ 完了 | `src/generate_actions.py`。既定 OpenAI（両キー時）。`temperature` は送らない（`gpt-5.5` 等の制約）。**2026-05-11** GitHub Actions・HTML 反映まで確認済み。`--soft-fail` 可 |
| **9** | **Slack Incoming Webhook** で URL とサマリー投稿 | ✅ 完了 | `src/post_slack.py`・`SLACK_WEBHOOK_URL`。Pages デプロイ直後に通知。未設定時はスキップ |
| **10** | **ShopifyQL + `read_reports`**（GraphQL `shopifyqlQuery`、Admin API **2025-10+**）でセッション数・CV率（注文÷セッション）を実数化 | ✅ 実装済（**要**: アプリに `read_reports` を追加し **再インストール／トークン再発行**、Secrets の `SHOPIFY_API_VERSION` が 2025-10 未満なら更新） | `fetch_shopify.py` の `FROM sessions SHOW sessions …`。`read_customer_events` はセッション集計には不要 |

---

## おすすめの「最初のゴール」

**フェーズ1 → フェーズ2** をセットにすると進みやすいです。

1. ダミーの `report.json`（または `payload.json`）を1つ決める。
2. その JSON から `reference/abil-weekly-report.html` 相当のHTMLを生成する（Jinja2 など任意）。
3. 次に Shopify だけ本物の数値で JSON を埋める。

こうすると「見た目」と「データパイプライン」が同じ契約（JSON）でつながります。

---

## 後から決めること（メモ用）

- 週の定義（月曜始まりか、締め日は何時か）
- 目標値・閾値（広告費率、アラート条件）
- surge のドメイン命名規則
