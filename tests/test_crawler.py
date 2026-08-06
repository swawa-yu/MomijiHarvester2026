import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from src.crawler import MomijiCrawler
from src.exporter import Exporter
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


def top_page(*faculty_files):
    links = "".join(f'<a href="{name}">{name}</a>' for name in faculty_files)
    return f"""
    {links}
    <font size="+2">学部</font>
    <img src="syllabus_list.gif">教養教育<br>
    <font size="+2">大学院</font>
    <img src="syllabus_list.gif">大学院共通教育<br>
    """


def faculty_page(*subject_files):
    return "".join(f'<a href="{name}">{name}</a>' for name in subject_files)


def subject_page(year, code):
    return f"""
    <table>
      <tr><th>年度</th><td>{year}年度</td></tr>
      <tr><th>講義コード</th><td>{code}</td></tr>
    </table>
    """


class MemoryCrawler(MomijiCrawler):
    def __init__(
            self, base_url: str, output_dir: Path, responses,
            include_english: bool = False):
        super().__init__(
            base_url=base_url,
            output_dir=str(output_dir),
            include_english=include_english,
        )
        self.responses = responses
        self.fetch_order = []
        self.exporter = Exporter(str(output_dir))

    async def fetch_html(self, url: str) -> str:
        self.fetch_order.append(url)
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


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


def preflight_responses(base_url):
    shared = base_url + "2026_AA_10000100.html"
    first_only = base_url + "2026_AA_10000101.html"
    second_only = base_url + "2026_BB_10000102.html"
    return {
        base_url: top_page("2026_AA.html", "2026_BB.html"),
        base_url + "2026_AA.html": faculty_page(
            "2026_AA_10000100.html", "2026_AA_10000101.html"
        ),
        base_url + "2026_BB.html": faculty_page(
            "2026_AA_10000100.html", "2026_BB_10000102.html"
        ),
        shared: subject_page("2026", "10000100"),
        first_only: subject_page("2026", "10000101"),
        second_only: subject_page("2026", "10000102"),
    }


@pytest.mark.asyncio
async def test_dry_run_reports_preflight_without_detail_fetch_or_output(
        tmp_path: Path, capsys):
    base_url = "https://example.test/syllabus/"
    responses = preflight_responses(base_url)
    output_dir = tmp_path / "not-created" / "nested-output"
    crawler = MemoryCrawler(base_url, output_dir, responses)

    await crawler.run(dry_run=True)

    detail_urls = {url for url in responses if "_100001" in url}
    assert detail_urls.isdisjoint(crawler.fetch_order)
    assert not output_dir.exists()
    output = capsys.readouterr().out
    assert "academic year=2026年度" in output
    assert "candidate occurrences=4" in output
    assert "globally unique URLs=3" in output
    assert "duplicate occurrences=1" in output


@pytest.mark.asyncio
async def test_normal_run_deduplicates_globally_and_preserves_first_context(
        tmp_path: Path):
    base_url = "https://example.test/syllabus/"
    responses = preflight_responses(base_url)
    crawler = MemoryCrawler(base_url, tmp_path, responses)

    await crawler.run(max_subjects=2)

    shared = base_url + "2026_AA_10000100.html"
    first_only = base_url + "2026_AA_10000101.html"
    second_only = base_url + "2026_BB_10000102.html"
    assert crawler.fetch_order.count(shared) == 1
    assert crawler.fetch_order.count(first_only) == 1
    assert crawler.fetch_order.count(second_only) == 0
    manifest = json.loads(
        (tmp_path / "subjectDataManifest.json").read_text(encoding="utf-8")
    )
    data = json.loads(
        (tmp_path / manifest["dataFile"]).read_text(encoding="utf-8")
    )
    assert list(data) == ["10000100", "10000101"]
    assert data["10000100"]["開講部局"] == "2026_AA"


@pytest.mark.asyncio
@pytest.mark.parametrize("responses_factory, error_type, message", [
    (
        lambda base: {
            base: top_page("2026_AA.html", "2025_BB.html"),
            base + "2026_AA.html": faculty_page("2026_AA_10000100.html"),
            base + "2025_BB.html": faculty_page("2025_BB_10000101.html"),
        },
        ValueError,
        "expected exactly one academic year",
    ),
    (
        lambda base: {
            base: top_page("2026_AA.html"),
            base + "2026_AA.html": '<a href="not-a-subject.html">none</a>',
        },
        RuntimeError,
        "Preflight failed.*No subject URLs found",
    ),
])
async def test_preflight_rejects_mixed_or_absent_year_before_details(
        tmp_path: Path, responses_factory, error_type, message):
    base_url = "https://example.test/syllabus/"
    crawler = MemoryCrawler(base_url, tmp_path, responses_factory(base_url))

    with pytest.raises(error_type, match=message):
        await crawler.run()

    assert not any("_100001" in url for url in crawler.fetch_order)
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_faculty_candidate_failure_aborts_before_details_or_output(
        tmp_path: Path):
    base_url = "https://example.test/syllabus/"
    output_dir = tmp_path / "output"
    good_detail = base_url + "2026_AA_10000100.html"
    responses = {
        base_url: top_page("2026_AA.html", "2026_BB.html"),
        base_url + "2026_AA.html": faculty_page("2026_AA_10000100.html"),
        base_url + "2026_BB.html": OSError("faculty page unavailable"),
        good_detail: subject_page("2026", "10000100"),
    }
    crawler = MemoryCrawler(base_url, output_dir, responses)

    with pytest.raises(RuntimeError, match="Preflight failed.*2026_BB.html"):
        await crawler.run()

    assert good_detail not in crawler.fetch_order
    assert not output_dir.exists()


@pytest.mark.asyncio
async def test_distinct_urls_with_same_subject_code_abort_before_export(
        tmp_path: Path):
    base_url = "https://example.test/syllabus/"
    output_dir = tmp_path / "output"
    first_name = "2026_AA_10000100.html"
    second_name = "2026_BB_10000101.html"
    first_url = base_url + first_name
    second_url = base_url + second_name
    responses = {
        base_url: top_page("2026_AA.html"),
        base_url + "2026_AA.html": faculty_page(first_name, second_name),
        first_url: subject_page("2026", "10000100"),
        second_url: subject_page("2026", "10000100"),
    }
    crawler = MemoryCrawler(base_url, output_dir, responses)

    with pytest.raises(ValueError, match="Subject code collision") as error:
        await crawler.run(max_subjects=0)

    assert first_url in str(error.value)
    assert second_url in str(error.value)
    assert crawler.fetch_order.count(first_url) == 1
    assert crawler.fetch_order.count(second_url) == 1
    assert not output_dir.exists()


@pytest.mark.asyncio
async def test_include_english_fails_before_network_or_output(tmp_path: Path):
    base_url = "https://example.test/syllabus/"
    output_dir = tmp_path / "output"
    crawler = MemoryCrawler(
        base_url,
        output_dir,
        responses={},
        include_english=True,
    )

    with pytest.raises(ValueError, match="include_english is unsupported"):
        await crawler.run()

    assert crawler.fetch_order == []
    assert not output_dir.exists()
