# データ取得・更新の運用方針

最終更新日: 2026-08-16

この文書は、広島大学MOMIJIからシラバスを取得し、momiji2へ反映する際の
運用方針を記録するものです。利用許諾を改めて判断するための文書ではなく、
サイトへ過度な負荷をかけないこと、不完全なデータを公開しないこと、更新経路を
明確にすることを目的としています。

## 大学への確認

サービスの公開開始時に、私が広島大学へ問い合わせ、現在行っているシラバスの
機械取得とサービス公開について問題ないことを確認済みです。

問い合わせ本文や回答の詳細は、この公開リポジトリには掲載しません。確認済みの
範囲を越える用途へ推測で拡張せず、取得頻度や並列数を変更する場合は改めて影響を
確認します。

## 取得時に守ること

- 全件取得前に、年度、候補数、重複数を事前確認する。
- リクエスト間隔、限定的なretry、`Retry-After`を尊重する。
- 取得対象を全件処理できた場合だけ新しい成果物を生成する。
- 年度の混在、未知のHTML項目、異常な件数差、未分類値を検出した場合は停止する。
- 年度、取得日、件数、生成元、SHA-256をmanifestへ記録する。
- 取得元として広島大学MOMIJIを明示する。

## GitHub Actionsによる更新

`Create guarded momiji2 data update` workflowは、現在は`workflow_dispatch`による
手動起動だけに対応しています。

- `consumer-preflight`: クロールせず、Harvesterのテストとmomiji2側のデータ契約、
  型、生成物、ビルドを確認する。
- `full`: 日本語シラバスを全件取得し、producerとconsumerのすべてのguardを通過した
  場合だけ、momiji2の`develop`向け更新branchと確認用PRを作成する。

クロールで生成したJSONは、Actions runnerの一時ディレクトリに置かれます。すべての
検証に合格した場合だけ、JSON、manifest、分類データ等をmomiji2の更新branchへ
commitします。MomijiHarvester2026側のbranch、Release、Actions artifact、外部storageへ
JSONを永続保存する機能はありません。

workflowはPRを自動mergeせず、GitHub Pagesへ直接deployしません。確認後に更新PRを
momiji2へmergeすると、momiji2側のdeploy workflowが開発版へ反映します。

consumerへの書込みには、momiji2だけへ導入したGitHub Appの短命トークンを使用します。
秘密鍵はActions secret `MOMIJI2_UPDATER_PRIVATE_KEY`、Client IDはActions variable
`MOMIJI2_UPDATER_CLIENT_ID`で管理し、鍵やトークンをリポジトリへ保存しません。

## まだ自動化していないこと

- 定期実行（`schedule`）
- 更新PRの自動merge
- GitHub Pagesへの直接deploy
- producer側でのJSONの永続保存

定期実行は、手動の全件更新が複数回安定し、年度内変更履歴の生成とconsumer側の表示・
検証が完成した後に追加します。定期実行でも、異常時にはPRを作らず既存データを維持する
境界を変えません。

## 参照先

- https://momiji.hiroshima-u.ac.jp/robots.txt
- https://momiji.hiroshima-u.ac.jp/syllabusHtml/
- https://www.hiroshima-u.ac.jp/node/15230
