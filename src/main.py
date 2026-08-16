import asyncio
import json
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
    include_english: bool = typer.Option(
        False,
        help="現在未対応。英語版は将来、英語版トップを起点に別契約で取得する",
    ),
    dry_run: bool = typer.Option(False, help="実際の出力を行わずに動作確認する"),
) -> None:
    crawler = MomijiCrawler(base_url=base_url, output_dir=output_dir, include_english=include_english)
    asyncio.run(crawler.run(max_subjects=max_subjects, dry_run=dry_run))


async def _list_departments_async(base_url: str, output_file: str) -> None:
    crawler = MomijiCrawler(base_url=base_url)
    try:
        department_lists = await crawler.collect_department_lists()
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(department_lists, f, ensure_ascii=False, indent=2)
        typer.echo(f"Wrote department lists to {output_path}")
    finally:
        await crawler.client.close()


@app.command()
def list_departments(
    base_url: str = typer.Option(
        "https://momiji.hiroshima-u.ac.jp/syllabusHtml/", help="シラバストップページURL"
    ),
    output_file: str = typer.Option(
        "output/department_constants.json",
        help="出力先JSONファイルパス",
    ),
) -> None:
    asyncio.run(_list_departments_async(base_url=base_url, output_file=output_file))


@app.command()
def print_version() -> None:
    typer.echo("MomijiHarvester2026 0.1.0")


if __name__ == "__main__":
    app()
