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
        seen = set()

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
                if full_url not in seen:
                    seen.add(full_url)
                    links.append(full_url)
                self.subject_link_status[full_url] = "accepted"
            else:
                self.subject_link_status[href] = "rejected:pattern"

        if not links:
            raise ValueError(f"No subject URLs found in faculty page {faculty_url}. Check HTML structure.")
        return links

    async def process_subject(self, subject_url: str, faculty_name: str) -> SubjectDetails:
        html = await self.fetch_html(subject_url)
        relative_url = subject_url.replace(self.config.base_url, "")
        subject = Parser.parse_subject_page(html, relative_url, faculty_name)
        return subject

    async def run(self, max_subjects: int = 20, dry_run: bool = False):
        try:
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
                except ValueError as e:
                    print(f"WARNING: {e}", file=sys.stderr)
                    continue
                subject_batches.append((faculty_url, faculty_name, subject_urls))

            total_subjects = sum(len(urls) for _, _, urls in subject_batches)
            print(f"Found {len(subject_batches)} faculties and {total_subjects} subject pages.")

            with tqdm(total=total_subjects, desc="Parsing subjects", unit="lecture", dynamic_ncols=True, miniters=1, file=sys.stdout) as bar:
                processed = 0
                for faculty_url, faculty_name, subject_urls in subject_batches:
                    bar.set_description(f"Parsing {faculty_name}")
                    accepted_count = len(subject_urls)
                    rejected_count = sum(
                        1
                        for url, status in self.subject_link_status.items()
                        if status != "accepted" and (url.startswith(faculty_url) or not url.startswith("http"))
                    )
                    print(f"Subject URL status for {faculty_url}:")
                    print(f"  Subject candidates: {accepted_count} (accepted {accepted_count}, rejected {rejected_count})")
                    parsed_count_before = len(result)

                    for subject_url in subject_urls:
                        if max_subjects > 0 and len(result) >= max_subjects:
                            break
                        try:
                            subject = await self.process_subject(subject_url, faculty_name)
                            result[subject.code] = subject
                        except Exception as e:
                            print(f"Failed to process {subject_url}: {e}")
                        processed += 1
                        bar.update(1)
                        sys.stdout.write(f"\rProcessed {processed}/{total_subjects} subjects")
                        sys.stdout.flush()

                    parsed_count_after = len(result)
                    print(f"\n  Parsed subjects for {faculty_name}: {parsed_count_after - parsed_count_before}")
                    if max_subjects > 0 and len(result) >= max_subjects:
                        break

            if dry_run:
                print(f"Dry run complete. {len(result)} subjects parsed.")
                return

            lang_tag = "_en" if self.include_english else ""
            output_path = self.exporter.export(
                result,
                lang_tag=lang_tag,
                source=self.config.base_url,
                departments=departments,
            )
            print(f"Exported {len(result)} subjects to {output_path}")
        finally:
            await self.client.close()
