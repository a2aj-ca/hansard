from __future__ import annotations

import logging
from collections import deque
from typing import Optional

from .adapters.base import HansardAdapter
from .common.schema import DayPage
from .common.http import build_proxies, fetch, sleep, utc_now
from .common.mongo import (
    ensure_indexes,
    existing_day_urls,
    html_col,
    parsed_col,
    save_day_html_snapshot,
    save_pdf_metadata,
)

logger = logging.getLogger(__name__)


def _fetch_days(
    adapter: HansardAdapter,
    batch: str,
    day_refs: list[DayPage],
    download_pdfs: bool,
    proxies,
) -> int:
    """Fetch and store each day page, expanding into extra sittings as we go."""
    queue = deque(day_refs)
    seen = {d.url for d in day_refs}
    done = extra_found = 0

    while queue:
        day = queue.popleft()
        done += 1
        sleep(1, 2)
        logger.info("(%d/%d) Fetch day: %s", done, len(seen), day.url)
        dr = fetch(day.url, proxies=proxies)
        if not dr.ok or not dr.content:
            logger.warning("Failed day: %s", day.url)
            continue

        for sibling in adapter.extract_related_day_urls(dr.content, day.url):
            if sibling in seen:
                continue
            seen.add(sibling)
            extra_found += 1
            queue.append(DayPage(url=sibling, language=day.language))
            logger.info("Found additional sitting: %s (via %s)", sibling, day.url)

        pdf_links = adapter.extract_pdf_links(dr.content, day.url) if download_pdfs else []
        save_day_html_snapshot(
            batch=batch,
            day_url=day.url,
            result=dr,
            pdf_links=pdf_links if download_pdfs else None,
            language=day.language,
            jurisdiction=adapter.jurisdiction,
        )

        if download_pdfs:
            for pdf_url in pdf_links:
                sleep()
                pr = fetch(pdf_url, proxies=proxies, retries=4, timeout_s=60)
                if not pr.ok or not pr.content:
                    logger.warning("Failed PDF: %s", pdf_url)
                    continue
                save_pdf_metadata(batch, day.url, pdf_url, pr)

    logger.info("Fetched %d day pages (%d were additional sittings)", done, extra_found)
    return extra_found


def run_discover_and_fetch(
    adapter: HansardAdapter,
    batch: str,
    mode: str = "full",
    download_pdfs: bool = True,
    since: Optional[str] = None,
    recheck: int = 14,
) -> None:
    """Stage 1+2: discover day URLs (via adapter) and fetch their HTML + PDFs."""
    proxies = build_proxies()
    day_refs = adapter.discover(mode=mode)

    if since:
        before = len(day_refs)
        # keep days on/after `since`; keep undatable days so we never silently drop them
        day_refs = [d for d in day_refs if d.date is None or d.date >= since]
        logger.info("Since filter >= %s: %d -> %d day URLs", since, before, len(day_refs))
    

    if mode == "incremental":
        # skip URLs already in the db so we only fetch genuinely new days.
        # "refresh" deliberately skips this filter to re-fetch existing days.
        known = existing_day_urls([d.url for d in day_refs])
        # An evening sitting is often published a day or two after the afternoon one, 
        # by which time the afternoon page is already "known" and would be skipped. 
        # So the newest`recheck` days are always re-fetched.
        recent = {d.url for d in day_refs[-recheck:]} if recheck else set()
        day_refs = [d for d in day_refs if d.url not in known or d.url in recent]
        logger.info("Incremental mode: %d day URLs to fetch (including up to %d recent re-checks)", len(day_refs), recheck)

    _fetch_days(adapter, batch, day_refs, download_pdfs, proxies)


def run_backfill_sittings(
    adapter: HansardAdapter,
    batch: str,
    download_pdfs: bool = True,
) -> None:
    """Recover extra sittings that earlier runs missed, without re-crawling.

    Every stored day page already contains the links to its own sibling sittings,
    so we can find what was missed by re-reading HTML we hold and only going to
    the network for the pages that are genuinely absent.
    """
    proxies = build_proxies()
    logger.info("Scanning stored snapshots for unfetched sittings | adapter=%s", adapter.name)

    cursor = html_col.find(
        {"jurisdiction": adapter.jurisdiction},
        {"url": 1, "content": 1, "language": 1},
    )

    candidates: dict[str, str] = {}   # url -> language
    scanned = 0
    for doc in cursor:
        content = doc.get("content")
        url = doc.get("url")
        if not content or not url:
            continue
        scanned += 1
        language = doc.get("language") or "en"
        for sibling in adapter.extract_related_day_urls(content, url):
            candidates.setdefault(sibling, language)

    known = existing_day_urls(list(candidates))
    missing = [DayPage(url=u, language=lang) for u, lang in sorted(candidates.items()) if u not in known]
    logger.info(
        "Scanned %d snapshots | %d sibling sittings linked | %d missing",
        scanned, len(candidates), len(missing),
    )

    if not missing:
        logger.info("Backfill: nothing to fetch")
        return

    _fetch_days(adapter, batch, missing, download_pdfs, proxies)


def run_parse(adapter: HansardAdapter) -> None:
    """Stage 3+4: parse every unparsed snapshot and store rows."""
    logger.info("Starting parse run | adapter=%s", adapter.name)

    ok = failed = total_rows = 0
    query = {"parsed": {"$ne": True}, "jurisdiction": adapter.jurisdiction}
    cursor = html_col.find(query, {"url": 1, "content": 1, "language": 1})

    for i, doc in enumerate(cursor, start=1):
        url = doc.get("url")
        content = doc.get("content")
        language = doc.get("language") or (adapter.supported_languages[0] if adapter.supported_languages else "en")

        if content is None:
            failed += 1
            html_col.update_one(
                {"_id": doc["_id"]},
                {"$set": {"parsed": False, "parse_error": "Missing content"}},
            )
            logger.warning("Missing content | url=%s", url)
            continue

        try:
            rows = adapter.parse(content, language=language)
            # attach source metadata before inserting
            for row in rows:
                row["source_url"] = url
            # clear any prior rows for this day so a re-parse can't leave orphans
            # (e.g. when a corrected transcript yields fewer rows than before)
            parsed_col.delete_many({"source_url": url})
            if rows:
                parsed_col.insert_many(rows, ordered=False)

            html_col.update_one(
                {"_id": doc["_id"]},
                {"$set": {"parsed": True, "parsed_at": utc_now(), "parse_error": None}},
            )
            ok += 1
            total_rows += len(rows)
            logger.info("Parsed OK | i=%d | url=%s | rows=%d", i, url, len(rows))

        except Exception as e:
            failed += 1
            html_col.update_one(
                {"_id": doc["_id"]},
                {"$set": {"parsed": False, "parse_error": str(e)}},
            )
            logger.exception("Parse failed | i=%d | url=%s", i, url)

    logger.info("Finished parse run | ok=%d | failed=%d | total_rows=%d", ok, failed, total_rows)


def run_pipeline(
    adapter: HansardAdapter,
    stage: str = "all",
    batch: str = "default",
    mode: str = "full",
    download_pdfs: bool = True,
    since: Optional[str] = None,
    limit_days: Optional[int] = None,
    recheck: int = 14,
) -> None:
    ensure_indexes()

    if stage in ("all", "fetch", "discover"):
        run_discover_and_fetch(
            adapter=adapter,
            batch=batch,
            mode=mode,
            download_pdfs=download_pdfs,
            since=since,
            recheck=recheck,
        )

    if stage in ("all", "parse"):
        run_parse(adapter)
