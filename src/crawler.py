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


class MomijiCrawler:
    def __init__(self, base_url: str, output_dir: str = "output"):
        self.config = ScraperConfig(base_url=base_url, output_dir=output_dir)
        self.client = HttpClient(self.config)
        self.parser = Parser()
        self.exporter = Exporter(output_dir=self.config.output_dir)

    async def fetch_html(self, url: str) -> str:
        response = await self.client.get(url)
        await asyncio.sleep(self.config.rate_limit_seconds)
        return response.text

    async def collect_faculty_urls(self) -> List[str]:
        html = await self.fetch_html(self.config.base_url)
        soup = Parser.get_html_soup(html)

        faculty_pattern = re.compile(r"^\d{4}_[A-Za-z0-9]+\.html$")
        links = []

        for a in soup.select("a[href]"):
            href = a.get("href")
            if not href or not href.endswith(".html"):
                continue
            if href.lower().endswith("index.html"):
                continue
            if faculty_pattern.match(href):
                links.append(urljoin(self.config.base_url, href))

        links = sorted(set(links))
        if not links:
            raise ValueError("No faculty URLs found in page structure. Check HTML structure.")
        return links

    async def collect_subject_urls(self, faculty_url: str) -> List[str]:
        html = await self.fetch_html(faculty_url)
        soup = Parser.get_html_soup(html)

        subject_pattern = re.compile(r"^\d{4}_[A-Za-z0-9]+_\d{8}\.html$")
        links = []

        for a in soup.select("a[href]"):
            href = a.get("href")
            if not href or not href.endswith(".html"):
                continue
            if href.lower().endswith("index.html"):
                continue
            if subject_pattern.match(href):
                links.append(urljoin(faculty_url, href))

        links = sorted(set(links))
        if not links:
            raise ValueError(f"No subject URLs found in faculty page {faculty_url}. Check HTML structure.")
        return links

    async def process_subject(self, subject_url: str, faculty_name: str) -> SubjectDetails:
        html = await self.fetch_html(subject_url)
        relative_url = subject_url.replace(self.config.base_url, "")
        subject = Parser.parse_subject_page(html, relative_url, faculty_name)
        return subject

    async def run(self, max_subjects: int = 0, dry_run: bool = False):
        try:
            faculty_urls = await self.collect_faculty_urls()
            result: Dict[str, SubjectDetails] = {}
            for faculty_url in faculty_urls:
                faculty_name = faculty_url.split("/")[-1].replace(".html", "")
                subject_urls = await self.collect_subject_urls(faculty_url)
                for subject_url in subject_urls:
                    if max_subjects > 0 and len(result) >= max_subjects:
                        break
                    try:
                        subject = await self.process_subject(subject_url, faculty_name)
                        result[subject.code] = subject
                    except Exception as e:
                        print(f"Failed to process {subject_url}: {e}", file=sys.stderr)
                if max_subjects > 0 and len(result) >= max_subjects:
                    break

            if dry_run:
                print(f"Dry run complete. {len(result)} subjects parsed.")
                return

            output_path = self.exporter.export(result)
            print(f"Exported {len(result)} subjects to {output_path}")
        finally:
            await self.client.close()
