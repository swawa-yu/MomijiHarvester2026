# MomijiHarvester2026

広島大学シラバスサイト（https://momiji.hiroshima-u.ac.jp/syllabusHtml/）から授業情報をスクレイピングし、JSON出力するプロジェクトです。

## 目的

- 学部/授業ページを順にたどり、科目詳細データを取得
- 検証済みJSONを`subject_details_main_<YYYY-MM-DD>[_<lang>]_<sha256-prefix-12>.json`形式で世代別保存
- 同じ出力ディレクトリにmomiji2互換の`subjectDataManifest.json`も保存
- 今後GitHub Actionsによる定期実行を想定

## 機能

1. トップページ -> 学部ページ -> 授業詳細ページのクロール
2. データ整形とバリデーション（pydantic利用予定）
3. 出力ファイル名は内容ハッシュ付きの世代別JSON
4. rate limit: 0.1秒/リクエスト

## 開発環境

- Python 3.11+ を想定
- venvを使わず `uv` を利用した環境構築（要 `uv` コマンド）

## uvベースのセットアップ

```bash
# uv がインストール済みである前提
uv init  # VEnvを作成または既存環境をPATHに追加
uv install -r requirements.txt
```

※ `uv` の使い方は環境により異なる場合があります。`uv --help`で確認してください。

## 実行方法（開発中のコマンド）

```bash
uv run python -m src.main
```

開講部局一覧を出力する場合:

```bash
uv run python -m src.main list-departments
```

デフォルトでは `output/department_constants.json` に `kaikouBukyokuGakubus` と `kaikouBukyokuDaigakuins` を出力します。

通常の `run` は、科目JSONと同じトップページ取得結果から部局一覧も抽出します。対応する科目JSON世代名と、部局契約内容のSHA-256先頭12文字を含む
`department_constants_subject_details_main_<YYYY-MM-DD>[_<lang>]_<subject-sha-prefix>_<department-envelope-sha-prefix>.json` を出力し、`schemaVersion`、年度、取得日、source、科目JSONの完全SHA-256・件数を含む契約として保存します。

各詳細ページで観測した見出しの出現件数・率と空値件数・率は、内容ハッシュ付きの`subject_structure_*.json`として保存します。manifestはこの構造reportのファイル名とSHA-256も保持し、科目JSON・部局成果物・構造reportをすべて出力した後に最後に更新されます。

部局成果物には安定ポインタを設けません。取り込む側はファイル名を再構成せず、対象ファイルの明示的なパスを選び、部局成果物内の契約を検証してください。

複数年度が掲載されている場合は、対象年度を明示して実行できます。

```bash
uv run python -m src.main run --target-year 2027 --output-dir output
```

指定時は、その年度の学部・科目URLと詳細本文だけを対象にします。未指定時は年度混在を停止します。

詳細ページの取得前に、全学部ページの候補URLを集計して年度、候補出現数、全体で一意なURL数、重複出現数を表示します。重複URLは最初に現れた学部情報を採用して1回だけ取得し、`--max-subjects` は一意なURLに対して適用します。`--dry-run` はこの事前集計までを行い、詳細ページの取得やファイル出力は行いません。年度が混在する場合や候補から年度を特定できない場合は、詳細ページ取得前に停止します。

HTTP 429、HTTP 5xx、タイムアウト・通信エラーだけを最大3回再試行します。待機は0.5秒から指数的に増やして最大4秒とし、常に通常のリクエスト間隔以上を確保します。429・5xxに有効な `Retry-After`（秒数またはHTTP-date）があればそれ以上待機しますが、安全上限は60秒です。無効または過去の値は無視します。その他のHTTP 4xxは再試行しません。予定した詳細ページが最終的に1件でも取得・解析できなかった場合、その実行は不完全として成果物を更新しません。`--max-subjects` で限定した開発用実行も、限定範囲の全件成功時だけ出力します。

`Create guarded momiji2 data update` は現在手動起動だけに対応しています。全件取得で生成したJSONはActions runnerの一時ディレクトリに置き、すべての検証に合格した場合だけ`momiji2`の更新branchへcommitして`develop`向け確認PRを作成します。定期実行、自動merge、直接deploy、producer側でのJSONの永続保存は行いません。GitHub Appの秘密鍵はActions secret `MOMIJI2_UPDATER_PRIVATE_KEY`、Client IDはActions variable `MOMIJI2_UPDATER_CLIENT_ID`として管理し、値をリポジトリへ保存しません。

`--include-english` は現在未対応で、通信開始前にエラー終了します。日本語版と英語版は同じ講義コードを持ち得るため混在させません。英語版は将来、英語版トップページを起点とする独立クロールと専用の出力契約として対応します。

## 同一年度の変更履歴

構造検証済みの同一年度スナップショット2件から、決定的な変更履歴artifactを生成できます。SHA-256はJSONの空白やキー順に依存しないcanonical形式で計算します。

```bash
PYTHONPATH=. uv run python scripts/subject_history.py diff \
  --base-data path/to/base.json \
  --base-manifest path/to/base-manifest.json \
  --target-data path/to/target.json \
  --target-manifest path/to/target-manifest.json \
  --output path/to/history.json

PYTHONPATH=. uv run python scripts/subject_history.py apply \
  --base-data path/to/base.json \
  --diff path/to/history.json \
  --output path/to/restored.json

PYTHONPATH=. uv run python scripts/subject_history.py verify \
  --base-data path/to/base.json \
  --diff path/to/history-1.json \
  --diff path/to/history-2.json
```

`verify`は差分chainを順方向に適用した後、before値を使って逆方向にも復元し、件数・年度・canonical SHA-256を検証します。このツールはまだ自動更新workflowへは接続していません。

momiji2へ履歴を保存する準備には`prepare_consumer_history.py`を使います。初回の構造検証済み世代を`data/history/<年度>/index.json`のbaselineにし、以後は既存chainを順逆に検証してから内容ハッシュ付き差分を追加します。indexは削除可能になった旧latestのファイル名も返しますが、現段階ではworkflowによる搬送・削除は行いません。

※ 実装後に詳細を調整します。

## テスト

```bash
uv run pytest
```

## 今後のTODO

- サンプルHTML（トップ/学部/授業）を `tests/sample/` に追加
- `src/scraper.py`、`src/parser.py`、`src/models.py` を実装
- GitHub Actionsワークフロー追加
- ロギングを実装
- 生成JSONスキーマと`pydantic`バリデーション
