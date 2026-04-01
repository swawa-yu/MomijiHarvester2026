import asyncio
import sys
from pathlib import Path

import typer
from src.crawler import MomijiCrawler

app = typer.Typer()


@app.command()
def run(
    base_url: str = typer.Option(
        "https://momiji.hiroshima-u.ac.jp/syllabusHtml/", help="シラバストップページURL"
    ),
    output_dir: str = typer.Option("output", help="JSON出力ディレクトリ"),
    max_subjects: int = typer.Option(20, help="取得上限(0は無制限; デフォルト20)"),
    dry_run: bool = typer.Option(False, help="実際の出力を行わずに動作確認する"),
) -> None:
    crawler = MomijiCrawler(base_url=base_url, output_dir=output_dir)
    asyncio.run(crawler.run(max_subjects=max_subjects, dry_run=dry_run))


@app.command()
def print_version() -> None:
    typer.echo("MomijiHarvester2026 0.1.0")


if __name__ == "__main__":
    app()
