import asyncio
import logging
from os import getenv

import aiohttp
import feedparser
from aiogram import Bot
from dotenv import load_dotenv

import db
import llm
from ui import safe_send_to

load_dotenv()

ADMIN_ID = int(getenv("ADMIN_ID", "0"))

MAX_ITEMS_PER_RUN = int(getenv("AUTOPILOT_MAX_ITEMS", "3"))

DEFAULT_SOURCES: list[tuple[str, str]] = [
    ("https://www.bleepingcomputer.com/feed/", "rss"),
    ("https://feeds.feedburner.com/TheHackersNews", "rss"),
    ("https://habr.com/ru/rss/hub/infosecurity/all/?fl=ru", "rss"),
    (
        "https://api.github.com/search/repositories?q=topic:security-tools&sort=updated&order=desc&per_page=10",
        "github",
    ),
    (
        "https://api.github.com/search/repositories?q=topic:osint&sort=updated&order=desc&per_page=10",
        "github",
    ),
]


async def seed_default_sources() -> None:
    existing = await db.list_sources()
    if existing:
        return

    for url, source_type in DEFAULT_SOURCES:
        await db.add_source(url=url, source_type=source_type)
    logging.info("Автопилот: добавлено %d источников по умолчанию", len(DEFAULT_SOURCES))


def _parse_feed_sync(url: str):
    return feedparser.parse(url)


async def _generate_and_send(bot: Bot, title: str, url: str, summary: str) -> None:
    try:
        post_text = await llm.generate_post(
            idea=title,
            search_results=[{"title": title, "body": summary, "href": url}],
        )
    except Exception:
        logging.exception("Автопилот: ошибка генерации поста для %s", url)
        return

    post = await db.create_post(title=title, content=post_text, source_url=url)
    await safe_send_to(bot, ADMIN_ID, post_text, post.id)


async def _check_rss_source(bot: Bot, url: str) -> int:
    try:
        feed = await asyncio.to_thread(_parse_feed_sync, url)
    except Exception:
        logging.exception("Автопилот: не смог разобрать RSS %s", url)
        return 0

    new_items = 0
    for entry in feed.entries:
        if new_items >= MAX_ITEMS_PER_RUN:
            break

        link = entry.get("link")
        if not link or await db.url_exists(link):
            continue

        title = entry.get("title", "Без названия")
        summary = entry.get("summary", "") or entry.get("description", "")

        await _generate_and_send(bot, title=title, url=link, summary=summary)
        new_items += 1

    return new_items


async def _check_github_source(bot: Bot, api_url: str) -> int:
    new_items = 0

    try:
        async with aiohttp.ClientSession(headers={"Accept": "application/vnd.github+json"}) as session:
            async with session.get(api_url) as resp:
                if resp.status != 200:
                    logging.warning("Автопилот: GitHub API вернул %s для %s", resp.status, api_url)
                    return 0
                data = await resp.json()
    except Exception:
        logging.exception("Автопилот: ошибка запроса к GitHub API %s", api_url)
        return 0

    for repo in data.get("items", []):
        if new_items >= MAX_ITEMS_PER_RUN:
            break

        link = repo.get("html_url")
        if not link or await db.url_exists(link):
            continue

        title = repo.get("full_name", "unknown/repo")
        summary = repo.get("description") or "Без описания в репозитории."

        await _generate_and_send(bot, title=title, url=link, summary=summary)
        new_items += 1

    return new_items


async def run_autopilot_check(bot: Bot) -> None:
    logging.info("Автопилот: начинаю проверку источников")
    sources = await db.list_active_sources()

    total_new = 0
    for source in sources:
        try:
            if source.source_type == "rss":
                total_new += await _check_rss_source(bot, source.url)
            elif source.source_type == "github":
                total_new += await _check_github_source(bot, source.url)
            else:
                logging.warning("Автопилот: неизвестный source_type %s (id=%s)", source.source_type, source.id)
        except Exception:
            logging.exception("Автопилот: ошибка при проверке источника id=%s (%s)", source.id, source.url)

    logging.info("Автопилот: проверка завершена, новых черновиков отправлено: %d", total_new)