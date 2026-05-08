# ABiL 週次レポート自動化

Shopify・広告（Meta / Google）の数値を集め、週次HTMLレポートを生成し、Slackへ届けるツールです。ABiL.SHOP（サウナ・ピックル等を含む**店舗横断**の数値）を想定したパイプラインとして、このフォルダで開発します。

## 新しいチャットで開いたとき（最初に読む）

1. このファイル（`README.md`）を開く。
2. [docs/ROADMAP.md](./docs/ROADMAP.md) で「今どのフェーズか」と次の一手を確認する。
3. 作業ログやメモは [docs/NOTES.md](./docs/NOTES.md) に追記する（任意）。

**プロジェクトの位置**

- ルート: `/Users/tsuyoshiyamada/Documents/ai-workbench/work/abil-weekly-automation/`
- **レポートのビジュアル完成形・仕組み図解のHTML**: [reference/](./reference/README.md)

**関連ワークスペース（ブランド・資料）**

- `/Users/tsuyoshiyamada/Documents/ai-workbench/work/abil-sauna/` — サウナブランド（図解・キャンペーン等）
- `/Users/tsuyoshiyamada/Documents/ai-workbench/work/abil-pickleball/` — ピックル等

週次自動化のコードを触るときは **このフォルダを Cursor のルートに開く**のが基本です。図解や企画と一緒に見るときだけ、ワークスペースに上記を追加してください。

**方針（すでに決まっていること）**

- コードと GitHub Actions のシークレットは**自分だけ**が管理する想定。
- マイルストーンの優先順位の提案は [docs/ROADMAP.md](./docs/ROADMAP.md) を参照。

## フォルダ構成

```
abil-weekly-automation/
├── README.md           ← このファイル（入口）
├── .env.example        ← 必要な環境変数の名前だけ（値は書かない）
├── reference/          ← 完成形HTML（週次レポート見本・4パーツ図解）。詳細は reference/README.md
├── docs/
│   ├── ROADMAP.md      ← フェーズ・優先順位
│   └── NOTES.md        ← 作業メモ（任意）
└── src/                ← Python（取得スクリプト・Sheets 追記・HTML 生成）。詳細は src/README.md
```

## 環境変数

ローカルではこのフォルダ直下に `.env` を作成し（`.gitignore` 済み）、[.env.example](./.env.example) を参考にキー名だけ合わせる。値はリポジトリにコミットしない。週次デプロイ用の **LLM（OpenAI / Anthropic）** と **Slack** の変数名も `.env.example` に記載あり。運用の区切り・再開メモは [docs/NOTES.md](./docs/NOTES.md) 先頭のチェックポイントを参照。

## 関連ファイル

| 場所 | 内容 |
|------|------|
| [reference/abil-weekly-report.html](./reference/abil-weekly-report.html) | 週次レポートのビジュアル完成形（テンプレ／見本） |
| [reference/report-automation-flow.html](./reference/report-automation-flow.html) | 自動化4パーツの図解 |

## 次に AI に依頼するときの例

- 「`abil-weekly-automation` の ROADMAP に沿って、フェーズ1の JSON スキーマとテンプレート注入の骨格を `src/` に書いて」
- 「Shopify Admin API から先週の売上だけ取るスクリプトを `src/` に追加して」
