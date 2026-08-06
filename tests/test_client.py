import httpx
import pytest
from pydantic import ValidationError

from src.client import HttpClient
from src.config import ScraperConfig


def config(**overrides):
    values = {
        "base_url": "https://example.test/",
        "max_retries": 3,
        "retry_initial_delay_seconds": 0.25,
        "retry_backoff_max_seconds": 0.5,
    }
    values.update(overrides)
    return ScraperConfig(**values)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 503])
async def test_retries_retryable_status_with_exponential_backoff(status):
    attempts = 0
    delays = []

    async def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts < 4:
            return httpx.Response(status, request=request)
        return httpx.Response(200, text="ok", request=request)

    async def sleep(delay):
        delays.append(delay)

    client = HttpClient(
        config(), sleep=sleep, transport=httpx.MockTransport(handler)
    )
    try:
        response = await client.get("https://example.test/resource")
    finally:
        await client.close()

    assert response.text == "ok"
    assert attempts == 4
    assert delays == [0.25, 0.5, 0.5]


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.ConnectError])
async def test_retries_timeout_and_transport_then_succeeds(error_type):
    attempts = 0
    delays = []

    async def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise error_type("temporary failure", request=request)
        return httpx.Response(200, text="ok", request=request)

    async def sleep(delay):
        delays.append(delay)

    client = HttpClient(
        config(), sleep=sleep, transport=httpx.MockTransport(handler)
    )
    try:
        response = await client.get("https://example.test/resource")
    finally:
        await client.close()

    assert response.text == "ok"
    assert attempts == 3
    assert delays == [0.25, 0.5]


@pytest.mark.asyncio
async def test_retry_exhaustion_reraises_last_transport_error():
    errors = []
    delays = []

    async def handler(request):
        error = httpx.ReadTimeout("still unavailable", request=request)
        errors.append(error)
        raise error

    async def sleep(delay):
        delays.append(delay)

    client = HttpClient(
        config(max_retries=2),
        sleep=sleep,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(httpx.ReadTimeout) as caught:
            await client.get("https://example.test/resource")
    finally:
        await client.close()

    assert caught.value is errors[-1]
    assert len(errors) == 3
    assert delays == [0.25, 0.5]


@pytest.mark.asyncio
async def test_retryable_status_exhaustion_raises_final_http_error():
    attempts = 0
    delays = []

    async def handler(request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, request=request)

    async def sleep(delay):
        delays.append(delay)

    client = HttpClient(
        config(max_retries=1),
        sleep=sleep,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(httpx.HTTPStatusError) as caught:
            await client.get("https://example.test/resource")
    finally:
        await client.close()

    assert caught.value.response.status_code == 429
    assert caught.value.response.is_closed
    assert attempts == 2
    assert delays == [0.25]


@pytest.mark.asyncio
@pytest.mark.parametrize("retry_after, expected_delay", [
    ("3", 3.0),
    ("120", 60.0),
])
async def test_retry_after_delta_seconds_is_honored_and_capped(
        retry_after, expected_delay):
    attempts = 0
    delays = []

    async def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": retry_after},
                request=request,
            )
        return httpx.Response(200, request=request)

    async def sleep(delay):
        delays.append(delay)

    client = HttpClient(
        config(), sleep=sleep, transport=httpx.MockTransport(handler)
    )
    try:
        await client.get("https://example.test/resource")
    finally:
        await client.close()

    assert delays == [expected_delay]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "retry_after, expected_delay",
    [
        ("Fri, 01 Jan 2099 00:00:00 GMT", 60.0),
        ("Fri, 01 Jan 2099 00:00:00 -0000", 60.0),
        ("Sat, 01 Jan 2000 00:00:00 GMT", 0.25),
    ],
)
async def test_retry_after_http_date_is_honored_capped_or_expired(
        retry_after, expected_delay):
    attempts = 0
    delays = []

    async def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": retry_after},
                request=request,
            )
        return httpx.Response(200, request=request)

    async def sleep(delay):
        delays.append(delay)

    client = HttpClient(
        config(), sleep=sleep, transport=httpx.MockTransport(handler)
    )
    try:
        await client.get("https://example.test/resource")
    finally:
        await client.close()

    assert delays == [expected_delay]


@pytest.mark.asyncio
async def test_invalid_retry_after_falls_back_to_exponential_delay():
    attempts = 0
    delays = []

    async def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                503,
                headers={"Retry-After": "not-a-delay"},
                request=request,
            )
        return httpx.Response(200, request=request)

    async def sleep(delay):
        delays.append(delay)

    client = HttpClient(
        config(), sleep=sleep, transport=httpx.MockTransport(handler)
    )
    try:
        await client.get("https://example.test/resource")
    finally:
        await client.close()

    assert delays == [0.25]


@pytest.mark.asyncio
async def test_retry_sleep_never_undercuts_rate_limit():
    attempts = 0
    delays = []

    async def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("temporary failure", request=request)
        return httpx.Response(200, request=request)

    async def sleep(delay):
        delays.append(delay)

    client = HttpClient(
        config(rate_limit_seconds=0.75),
        sleep=sleep,
        transport=httpx.MockTransport(handler),
    )
    try:
        await client.get("https://example.test/resource")
    finally:
        await client.close()

    assert delays == [0.75]


@pytest.mark.asyncio
async def test_nonretryable_4xx_fails_immediately():
    attempts = 0
    delays = []

    async def handler(request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(404, request=request)

    async def sleep(delay):
        delays.append(delay)

    client = HttpClient(
        config(), sleep=sleep, transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(httpx.HTTPStatusError) as caught:
            await client.get("https://example.test/missing")
    finally:
        await client.close()

    assert caught.value.response.status_code == 404
    assert caught.value.response.is_closed
    assert attempts == 1
    assert delays == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("rate_limit_seconds", -0.1),
        ("rate_limit_seconds", float("nan")),
        ("rate_limit_seconds", float("inf")),
        ("retry_initial_delay_seconds", float("inf")),
        ("retry_backoff_max_seconds", float("inf")),
        ("retry_after_max_seconds", float("inf")),
    ],
)
def test_retry_timing_configuration_requires_finite_nonnegative_values(
        field, value):
    with pytest.raises(ValidationError):
        config(**{field: value})
