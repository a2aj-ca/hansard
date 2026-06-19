from __future__ import annotations

import logging
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Tunable, environment-specific defaults (see .env.example). The politeness delay
# between requests and the HTTP timeout/retry budget are operator knobs, not app
# logic, so they default here but can be overridden via the environment.
REQUEST_DELAY_MIN = float(os.getenv("REQUEST_DELAY_MIN", "1.0"))
REQUEST_DELAY_JITTER = float(os.getenv("REQUEST_DELAY_JITTER", "2.0"))
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "30"))
HTTP_RETRIES = int(os.getenv("HTTP_RETRIES", "4"))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def sleep(min_s: Optional[float] = None, jitter: Optional[float] = None) -> None:
    # called with no args for the inter-request politeness delay (env-configurable);
    # called with explicit args for retry backoff.
    if min_s is None:
        min_s = REQUEST_DELAY_MIN
    if jitter is None:
        jitter = REQUEST_DELAY_JITTER
    time.sleep(min_s + random.random() * jitter)


def build_proxies() -> Optional[dict]:
    proxy = os.getenv("PROXY")
    user = os.getenv("PROXY_USERNAME")
    pw = os.getenv("PROXY_PASSWORD")
    if not (proxy and user and pw):
        return None
    return {scheme: f"http://{user}:{pw}@{proxy}" for scheme in ("http", "https")}


@dataclass
class FetchResult:
    ok: bool
    url: str
    final_url: str
    status: Optional[int]
    content: Optional[bytes]
    headers: Optional[dict]
    error: Optional[str]
    fetched_at: datetime

def fetch(
    url: str,
    proxies: Optional[dict] = None,
    retries: int = HTTP_RETRIES,
    timeout_s: int = HTTP_TIMEOUT,
) -> FetchResult:
    
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, timeout=timeout_s, proxies=proxies, allow_redirects=True)

            if resp.status_code in (429, 503, 502, 504):
                logger.info("Status %s attempt %s | %s", resp.status_code, attempt, url)
                sleep(10 * attempt, 10)
                continue

            if resp.ok:
                return FetchResult(
                    ok=True,
                    url=url,
                    final_url=str(resp.url),
                    status=resp.status_code,
                    content=resp.content,
                    headers=dict(resp.headers),
                    error=None,
                    fetched_at=utc_now(),
                )

            logger.info("Status %s attempt %s | %s", resp.status_code, attempt, url)
            sleep(5 * attempt, 5)

        except Exception as exc:
            logger.info("Request error attempt %s | %s | %s", attempt, url, exc)
            sleep(5 * attempt, 5)

    return FetchResult(
        ok=False,
        url=url,
        final_url=url,
        status=None,
        content=None,
        headers=None,
        error=f"Failed after {retries} retries",
        fetched_at=utc_now(),
    )
