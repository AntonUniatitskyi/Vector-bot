import asyncio
from os import getenv
from ddgs import DDGS
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()

SEARCH_REGION = getenv("SEARCH_REGION", "wt-wt")
_raw_blocked = getenv("BLOCKED_DOMAINS", "ru")

BLOCKED_DOMAIN_SUFFIXES = tuple(
    d if d.startswith(".") else f".{d}"
    for d in (raw.strip().lower() for raw in _raw_blocked.split(","))
    if d
)

def _is_blocked(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    for suffix in BLOCKED_DOMAIN_SUFFIXES:
        if host == suffix.lstrip(".") or host.endswith(suffix):
            return True
    return False


def _search_sync(query: str, max_results: int) -> list[dict]:
    with DDGS() as ddgs:
        raw_results = list(ddgs.text(query, region=SEARCH_REGION, max_results=max_results * 2))

    filtered = [r for r in raw_results if not _is_blocked(r.get("href", ""))]
    return filtered[:max_results]


async def web_search(query: str, max_results: int = 5) -> list[dict]:
    return await asyncio.to_thread(_search_sync, query, max_results)