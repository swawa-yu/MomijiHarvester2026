import httpx
from src.config import ScraperConfig


class HttpClient:
    def __init__(self, config: ScraperConfig):
        self.config = config
        self.client = httpx.AsyncClient(
            headers={"User-Agent": config.user_agent},
            timeout=httpx.Timeout(config.timeout_seconds),
        )

    async def get(self, url: str) -> httpx.Response:
        response = await self.client.get(url)
        response.raise_for_status()
        return response

    async def close(self):
        await self.client.aclose()
