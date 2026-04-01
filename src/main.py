import asyncio
from src.crawler import MomijiCrawler


def main() -> None:
    crawler = MomijiCrawler(base_url="https://momiji.hiroshima-u.ac.jp/syllabusHtml/")
    asyncio.run(crawler.run())


if __name__ == "__main__":
    main()
