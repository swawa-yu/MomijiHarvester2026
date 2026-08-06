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
4. rate limit: 0.5秒/リクエスト

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

※ 実装後に詳細を調整します。

## テスト

```bash
uv run pytest
```

## 今後のTODO

- サンプルHTML（トップ/学部/授業）を `tests/sample/` に追加
- `src/scraper.py`、`src/parser.py`、`src/models.py` を実装
- GitHub Actionsワークフロー追加
- error retry とロギングを実装
- 生成JSONスキーマと`pydantic`バリデーション
