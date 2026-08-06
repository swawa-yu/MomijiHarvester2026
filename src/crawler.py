import asyncio
import re
import sys
from urllib.parse import urljoin
from typing import List, Dict

from src.client import HttpClient
from src.config import ScraperConfig
from src.parser import Parser
from src.exporter import Exporter
from src.models import SubjectDetails
from tqdm import tqdm


class MomijiCrawler:
    def __init__(self, base_url: str, output_dir: str = "output", include_english: bool = False):
        self.config = ScraperConfig(base_url=base_url, output_dir=output_dir)
        self.client = HttpClient(self.config)
        self.parser = Parser()
        self.exporter = Exporter(output_dir=self.config.output_dir)
        self.include_english = include_english
        self.faculty_link_status: Dict[str, str] = {}
        self.subject_link_status: Dict[str, str] = {}

    async def fetch_html(self, url: str) -> str:
        response = await self.client.get(url)
        await asyncio.sleep(self.config.rate_limit_seconds)
        return response.text

    def collect_faculty_urls_from_html(self, html: str) -> List[str]:
        soup = Parser.get_html_soup(html)

        faculty_pattern = re.compile(r"^\d{4}_[A-Za-z0-9]+(?:_en)?\.html$")
        links = []
        seen = set()

        for a in soup.select("a[href]"):
            href = a.get("href")
            if not href:
                continue
            if not href.endswith(".html"):
                self.faculty_link_status[href] = "rejected:not html"
                continue
            if href.lower().endswith("index.html"):
                self.faculty_link_status[href] = "rejected:index"
                continue
            if faculty_pattern.match(href):
                full_url = urljoin(self.config.base_url, href)
                if full_url not in seen:
                    seen.add(full_url)
                    links.append(full_url)
                self.faculty_link_status[full_url] = "accepted"
            else:
                self.faculty_link_status[href] = "rejected:pattern"

        if not links:
            raise ValueError("No faculty URLs found in page structure. Check HTML structure.")

        return links

    async def collect_faculty_urls(self) -> List[str]:
        html = await self.fetch_html(self.config.base_url)
        return self.collect_faculty_urls_from_html(html)

    async def collect_department_lists(self) -> dict[str, list[str]]:
        html = await self.fetch_html(self.config.base_url)
        return Parser.parse_department_lists(html)

    async def collect_subject_urls(self, faculty_url: str) -> List[str]:
        html = await self.fetch_html(faculty_url)
        soup = Parser.get_html_soup(html)

        self.subject_link_status = {}
        # 例: 2026_01_AQH00101.html, 2026_AA_10000100.html
        subject_pattern = re.compile(r"^\d{4}_[A-Za-z0-9]+_[A-Za-z0-9]+\.html$")
        links = []

        for a in soup.select("a[href]"):
            href = a.get("href")
            if not href:
                continue
            if not href.endswith(".html"):
                self.subject_link_status[href] = "rejected:not html"
                continue
            if href.lower().endswith("index.html"):
                self.subject_link_status[href] = "rejected:index"
                continue
            if not self.include_english and href.endswith("_en.html"):
                self.subject_link_status[href] = "rejected:english"
                continue
            if subject_pattern.match(href):
                full_url = urljoin(faculty_url, href)
                # Keep every occurrence for preflight accounting. Global
                # deduplication happens after all faculty pages are inspected.
                links.append(full_url)
                self.subject_link_status[full_url] = "accepted"
            else:
                self.subject_link_status[href] = "rejected:pattern"

        if not links:
            raise ValueError(f"No subject URLs found in faculty page {faculty_url}. Check HTML structure.")
        return links

    @staticmethod
    def preflight_subject_urls(subject_batches):
        occurrences = []
        years = set()
        for _, faculty_name, subject_urls in subject_batches:
            for subject_url in subject_urls:
                filename = subject_url.rsplit("/", 1)[-1]
                match = re.match(
                    r"^(\d{4})_[A-Za-z0-9]+_[A-Za-z0-9]+\.html$",
                    filename,
                )
                if match:
                    years.add(match.group(1))
                occurrences.append((subject_url, faculty_name))

        if not occurrences or not years:
            raise ValueError(
                "Preflight failed: no academic year found in subject URL candidates."
            )
        if len(years) != 1:
            raise ValueError(
                "Preflight failed: expected exactly one academic year, found "
                f"{', '.join(sorted(years))}."
            )

        unique_subjects = []
        seen = set()
        for subject_url, faculty_name in occurrences:
            if subject_url in seen:
                continue
            seen.add(subject_url)
            unique_subjects.append((subject_url, faculty_name))

        total_occurrences = len(occurrences)
        return {
            "academicYear": f"{next(iter(years))}年度",
            "totalCandidateOccurrences": total_occurrences,
            "uniqueSubjectUrlCount": len(unique_subjects),
            "duplicateOccurrenceCount": total_occurrences - len(unique_subjects),
            "uniqueSubjects": unique_subjects,
        }

    async def process_subject(self, subject_url: str, faculty_name: str) -> SubjectDetails:
        html = await self.fetch_html(subject_url)
        relative_url = subject_url.replace(self.config.base_url, "")
        subject = Parser.parse_subject_page(html, relative_url, faculty_name)
        return subject

    async def run(self, max_subjects: int = 20, dry_run: bool = False):
        try:
            if self.include_english:
                raise ValueError(
                    "include_english is unsupported: Japanese and English "
                    "records must not be mixed. A separate English-base crawl "
                    "will require a dedicated output contract."
                )
            top_page_html = await self.fetch_html(self.config.base_url)
            faculty_urls = self.collect_faculty_urls_from_html(top_page_html)
            departments = Parser.parse_department_lists(top_page_html)
            result: Dict[str, SubjectDetails] = {}
            subject_batches = []

            print("Faculty URL status:")
            for url, status in self.faculty_link_status.items():
                print(f"  {status}: {url}")

            for faculty_url in faculty_urls:
                faculty_name = faculty_url.split("/")[-1].replace(".html", "")
                try:
                    subject_urls = await self.collect_subject_urls(faculty_url)
                except Exception as e:
                    raise RuntimeError(
                        "Preflight failed while collecting subject URL "
                        f"candidates from {faculty_url}: {e}"
                    ) from e
                subject_batches.append((faculty_url, faculty_name, subject_urls))

            preflight = self.preflight_subject_urls(subject_batches)
            print(
                "Preflight: "
                f"academic year={preflight['academicYear']}, "
                f"candidate occurrences={preflight['totalCandidateOccurrences']}, "
                f"globally unique URLs={preflight['uniqueSubjectUrlCount']}, "
                f"duplicate occurrences={preflight['duplicateOccurrenceCount']}."
            )

            if dry_run:
                print("Dry run complete. No detail pages fetched and no outputs written.")
                return

            unique_subjects = preflight["uniqueSubjects"]
            if max_subjects > 0:
                unique_subjects = unique_subjects[:max_subjects]

            subject_sources = {}
            failures = []
            with tqdm(total=len(unique_subjects), desc="Parsing subjects", unit="lecture", dynamic_ncols=True, miniters=1, file=sys.stdout) as bar:
                for processed, (subject_url, faculty_name) in enumerate(
                        unique_subjects, start=1):
                    bar.set_description(f"Parsing {faculty_name}")
                    try:
                        subject = await self.process_subject(subject_url, faculty_name)
                    except Exception as e:
                        print(f"Failed to process {subject_url}: {e}")
                        failures.append((subject_url, e))
                    else:
                        if subject.code in result:
                            previous_url, previous_faculty = subject_sources[
                                subject.code
                            ]
                            raise ValueError(
                                f"Subject code collision for {subject.code}: "
                                f"first {previous_url} ({previous_faculty}), "
                                f"then {subject_url} ({faculty_name})."
                            )
                        result[subject.code] = subject
                        subject_sources[subject.code] = (
                            subject_url,
                            faculty_name,
                        )
                    bar.update(1)
                    sys.stdout.write(
                        f"\rProcessed {processed}/{len(unique_subjects)} subjects"
                    )
                    sys.stdout.flush()

            if failures:
                representative_urls = ", ".join(
                    url for url, _ in failures[:5]
                )
                raise RuntimeError(
                    "Incomplete crawl: "
                    f"{len(failures)} of {len(unique_subjects)} planned detail "
                    "URLs failed; no outputs were updated. "
                    f"Representative URLs: {representative_urls}"
                )

            output_path = self.exporter.export(
                result,
                source=self.config.base_url,
                departments=departments,
            )
            print(f"Exported {len(result)} subjects to {output_path}")
        finally:
            await self.client.close()
