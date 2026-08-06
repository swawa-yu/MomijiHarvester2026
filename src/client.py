import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx
from src.config import ScraperConfig


class HttpClient:
    def __init__(
        self,
        config: ScraperConfig,
        sleep=asyncio.sleep,
        transport=None,
    ):
        self.config = config
        self.sleep = sleep
        self.client = httpx.AsyncClient(
            headers={"User-Agent": config.user_agent},
            timeout=httpx.Timeout(config.timeout_seconds),
            transport=transport,
        )

    async def get(self, url: str) -> httpx.Response:
        for attempt in range(self.config.max_retries + 1):
            try:
                response = await self.client.get(url)
            except (httpx.TimeoutException, httpx.TransportError):
                if attempt >= self.config.max_retries:
                    raise
                await self._sleep_before_retry(attempt)
                continue

            retryable_status = (
                response.status_code == 429
                or 500 <= response.status_code <= 599
            )
            if retryable_status and attempt < self.config.max_retries:
                retry_after = self._retry_after_seconds(response)
                await response.aclose()
                await self._sleep_before_retry(attempt, retry_after)
                continue

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError:
                await response.aclose()
                raise
            return response

        raise AssertionError("retry loop exhausted without returning or raising")

    async def _sleep_before_retry(
        self, attempt: int, retry_after: float = 0
    ) -> None:
        exponential_delay = min(
            self.config.retry_initial_delay_seconds * (2 ** attempt),
            self.config.retry_backoff_max_seconds,
        )
        delay = max(
            exponential_delay,
            self.config.rate_limit_seconds,
            min(retry_after, self.config.retry_after_max_seconds),
        )
        await self.sleep(delay)

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float:
        value = response.headers.get("Retry-After")
        if value is None:
            return 0
        value = value.strip()
        if value.isdigit():
            return float(value)
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return 0
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        seconds = (retry_at - datetime.now(timezone.utc)).total_seconds()
        return max(seconds, 0)

    async def close(self):
        await self.client.aclose()
