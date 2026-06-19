from __future__ import annotations

import logging
from typing import Optional

from .adapters.base import HansardAdapter
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


def run_discover_and_fetch(
    adapter: HansardAdapter,
    batch: str,
    mode: str = "full",
    download_pdfs: bool = True,
    since: Optional[str] = None,
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
        day_refs = [d for d in day_refs if d.url not in known]
        logger.info("Incremental mode: %d new day URLs", len(day_refs))

    # download each day html + PDFs
    for j, day in enumerate(day_refs, start=1):
        sleep()
        logger.info("(%d/%d) Fetch day: %s", j, len(day_refs), day.url)
        dr = fetch(day.url, proxies=proxies)
        if not dr.ok or not dr.content:
            logger.warning("Failed day: %s", day.url)
            continue

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
) -> None:
    ensure_indexes()

    if stage in ("all", "fetch", "discover"):
        run_discover_and_fetch(
            adapter=adapter,
            batch=batch,
            mode=mode,
            download_pdfs=download_pdfs,
            since=since,
        )

    if stage in ("all", "parse"):
        run_parse(adapter)
