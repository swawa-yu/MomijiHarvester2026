import asyncio
from urllib.parse import urljoin
from typing import List, Dict

from src.client import HttpClient
from src.config import ScraperConfig
from src.parser import Parser
from src.exporter import Exporter
from src.models import SubjectDetails


class MomijiCrawler:
    def __init__(self, base_url: str):
        self.config = ScraperConfig(base_url=base_url)
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

        links = []
        for a in soup.select("a[href]"):
            href = a.get("href")
            if not href or not href.endswith(".html"):
                continue
            if href.lower().endswith("index.html"):
                continue
            # トップページにある学部・学科ページへのリンク
            links.append(urljoin(self.config.base_url, href))

        # 重複除外
        return sorted(set(links))

    async def collect_subject_urls(self, faculty_url: str) -> List[str]:
        html = await self.fetch_html(faculty_url)
        soup = Parser.get_html_soup(html)

        links = []
        for a in soup.select("a[href]"):
            href = a.get("href")
            if not href or not href.endswith(".html"):
                continue
            # 学部/学科ページに掲載されている授業詳細ページ（例: 2026_AA_10000100.html）
            if href == "index.html" or href == faculty_url:
                continue
            if href.count("_") >= 2:
                links.append(urljoin(faculty_url, href))

        return sorted(set(links))

    async def process_subject(self, subject_url: str, faculty_name: str) -> SubjectDetails:
        html = await self.fetch_html(subject_url)
        relative_url = subject_url.replace(self.config.base_url, "")
        subject = Parser.parse_subject_page(html, relative_url, faculty_name)
        return subject

    async def run(self):
        try:
            faculty_urls = await self.collect_faculty_urls()
            result: Dict[str, SubjectDetails] = {}
            for faculty_url in faculty_urls:
                faculty_name = faculty_url.split("/")[-1].replace(".html", "")
                subject_urls = await self.collect_subject_urls(faculty_url)
                for subject_url in subject_urls:
                    subject = await self.process_subject(subject_url, faculty_name)
                    result[subject.code] = subject
            output_path = self.exporter.export(result)
            print(f"Exported {len(result)} subjects to {output_path}")
        finally:
            await self.client.close()
