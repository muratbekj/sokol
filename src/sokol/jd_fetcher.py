"""Fetch a job posting URL and extract the job description text."""

from __future__ import annotations

import httpx
import trafilatura

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class FetchFailed(Exception):
    """The URL could not be fetched or no usable job description was extracted."""


def fetch_job_description(url: str, min_chars: int) -> str:
    try:
        response = httpx.get(
            url, headers=HEADERS, follow_redirects=True, timeout=20.0
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise FetchFailed(f"Could not fetch the page: {exc}") from exc

    text = trafilatura.extract(
        response.text,
        url=url,
        favor_recall=True,
        include_comments=False,
        include_tables=True,
    )
    if not text or len(text) < min_chars:
        raise FetchFailed(
            "The page loaded but I couldn't extract a job description from it "
            "(it may be behind a login wall or rendered with JavaScript)."
        )
    return text.strip()
