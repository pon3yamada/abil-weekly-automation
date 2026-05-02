# reference/（静的HTMLの正）

週次レポート自動化プロジェクトで使う**完成形ビジュアル**と**仕組みの図解**を、このフォルダにまとめています。  
（以前は `output/` に置いていましたが、プロジェクト単位で管理するためここへ移しました。）

## ファイル

| ファイル | 役割 |
|----------|------|
| [abil-weekly-report.html](./abil-weekly-report.html) | **週次レポートのビジュアル完成形**（Tailwind CDN + Chart.js）。自動生成のテンプレート／見本として使う。 |
| [report-automation-flow.html](./report-automation-flow.html) | **自動化の4パーツ**（トリガー・ソース・処理・届け先）の図解。設計説明・社内共有用。 |

## ローカルで開く

ブラウザでファイルを開くか:

```bash
open /Users/tsuyoshiyamada/Documents/ai-workbench/work/abil-weekly-automation/reference/abil-weekly-report.html
open /Users/tsuyoshiyamada/Documents/ai-workbench/work/abil-weekly-automation/reference/report-automation-flow.html
```

## surge.sh で再デプロイするとき

図解用のデプロイスクリプトは、学習用リポジトリ `personal-visual-explainers` 側にあります。**HTML はこのプロジェクトの絶対パス**を渡してください。

```bash
bash /Users/tsuyoshiyamada/Documents/ai-workbench/learning/personal-visual-explainers/.claude/skills/creating-visual-explainers/scripts/deploy-diagram.sh \
  /Users/tsuyoshiyamada/Documents/ai-workbench/work/abil-weekly-automation/reference/abil-weekly-report.html \
  abil-weekly-report

bash /Users/tsuyoshiyamada/Documents/ai-workbench/learning/personal-visual-explainers/.claude/skills/creating-visual-explainers/scripts/deploy-diagram.sh \
  /Users/tsuyoshiyamada/Documents/ai-workbench/work/abil-weekly-automation/reference/report-automation-flow.html \
  report-automation-flow
```

過去に公開したURLの例（再デプロイで上書きされる場合があります）:

- 週次レポート: `https://diagram-abil-weekly-report.surge.sh`
- 仕組み図解: `https://diagram-report-automation-flow.surge.sh`
