import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from src.crawler import MomijiCrawler
from src.parser import Parser


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


class CountingLocalFileCrawler(LocalFileCrawler):
    def __init__(self, base_url: str, sample_root: Path, output_dir: Path):
        super().__init__(base_url=base_url, sample_root=sample_root)
        self.config.output_dir = str(output_dir)
        self.exporter = self.exporter.__class__(output_dir=str(output_dir))
        self.fetch_counts = {}

    async def fetch_html(self, url: str) -> str:
        self.fetch_counts[url] = self.fetch_counts.get(url, 0) + 1
        return await super().fetch_html(url)

    def collect_faculty_urls_from_html(self, html: str):
        # Keep this integration test offline and bounded to the one faculty
        # fixture while still requiring run() to parse departments from html.
        assert "syllabus_list.gif" in html
        return [self.config.base_url + "2026_AA.html"]


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


@pytest.mark.asyncio
async def test_run_uses_one_top_page_snapshot_for_faculties_and_departments(
        tmp_path: Path):
    base_url = "https://momiji.hiroshima-u.ac.jp/syllabusHtml/"
    crawler = CountingLocalFileCrawler(
        base_url=base_url,
        sample_root=Path("tests/sample"),
        output_dir=tmp_path,
    )

    await crawler.run(max_subjects=1)

    assert crawler.fetch_counts[base_url] == 1
    artifact_paths = list(tmp_path.glob("department_constants_*.json"))
    assert len(artifact_paths) == 1
    top_page_html = Path("tests/sample/index.html").read_text(encoding="utf-8")
    artifact = json.loads(artifact_paths[0].read_text(encoding="utf-8"))
    manifest = json.loads(
        (tmp_path / "subjectDataManifest.json").read_text(encoding="utf-8")
    )
    subject_bytes = (tmp_path / manifest["dataFile"]).read_bytes()
    assert artifact["departments"] == Parser.parse_department_lists(top_page_html)
    assert artifact["academicYear"] == manifest["academicYear"] == "2026年度"
    assert artifact["retrievedAt"] == manifest["retrievedAt"]
    assert artifact["source"] == manifest["source"] == base_url
    assert artifact["subjectData"] == {
        "dataFile": manifest["dataFile"],
        "sha256": hashlib.sha256(subject_bytes).hexdigest(),
        "subjectCount": manifest["subjectCount"],
    }
