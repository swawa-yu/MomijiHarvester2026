import asyncio
from pathlib import Path

import pytest
from src.crawler import MomijiCrawler


class LocalFileCrawler(MomijiCrawler):
    def __init__(self, base_url: str, sample_root: Path):
        super().__init__(base_url=base_url)
        self.sample_root = sample_root

    async def fetch_html(self, url: str) -> str:
        # URLは https://.../file.html の形で渡される想定
        filename = url.rstrip("/").split("/")[-1]
        if not filename or filename == "syllabusHtml":
            filename = "index.html"
        file_path = self.sample_root / filename
        return file_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_collect_faculty_urls_from_index_sample():
    crawler = LocalFileCrawler(
        base_url="https://momiji.hiroshima-u.ac.jp/syllabusHtml/",
        sample_root=Path("tests/sample"),
    )

    faculty_links = await crawler.collect_faculty_urls()

    assert "https://momiji.hiroshima-u.ac.jp/syllabusHtml/2026_AA.html" in faculty_links
    assert "https://momiji.hiroshima-u.ac.jp/syllabusHtml/2026_01.html" in faculty_links


@pytest.mark.asyncio
async def test_collect_subject_urls_from_faculty_sample():
    crawler = LocalFileCrawler(
        base_url="https://momiji.hiroshima-u.ac.jp/syllabusHtml/",
        sample_root=Path("tests/sample"),
    )

    subject_links = await crawler.collect_subject_urls(
        "https://momiji.hiroshima-u.ac.jp/syllabusHtml/2026_AA.html"
    )

    assert "https://momiji.hiroshima-u.ac.jp/syllabusHtml/2026_AA_10000100.html" in subject_links
    assert "https://momiji.hiroshima-u.ac.jp/syllabusHtml/2026_AA_10000103.html" in subject_links


@pytest.mark.asyncio
async def test_collect_department_lists_from_index_sample():
    crawler = LocalFileCrawler(
        base_url="https://momiji.hiroshima-u.ac.jp/syllabusHtml/",
        sample_root=Path("tests/sample"),
    )

    departments = await crawler.collect_department_lists()
    assert "教養教育" in departments["kaikouBukyokuGakubus"]
    assert "大学院共通教育（博士課程前期）" in departments["kaikouBukyokuDaigakuins"]
