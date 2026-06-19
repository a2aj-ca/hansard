from __future__ import annotations

from datetime import timezone
from typing import Optional
import os

from pymongo import ASCENDING, MongoClient

from .http import FetchResult, utc_now


_client = MongoClient(
    os.getenv("MONGO_URI", "mongodb://localhost:27017/"),
    tz_aware=True,
    tzinfo=timezone.utc,
)
db = _client[os.getenv("MONGO_DB_NAME", "hansard")]

html_col = db["hansard-html-snapshots"]
pdf_col = db["hansard-pdf-metadata"]
parsed_col = db["hansard-parsed-rows"]

# creates unique indexes on two collections and stops duplicate entries
def ensure_indexes() -> None:
    html_col.create_index([("batch", ASCENDING), ("url", ASCENDING)], unique=True)
    html_col.create_index([("url", ASCENDING)], unique=True, name="url_unique")
    pdf_col.create_index([("batch", ASCENDING), ("pdf_url", ASCENDING)], unique=True)
    parsed_col.create_index([("source_url", ASCENDING), ("ID", ASCENDING)], unique=True)


def save_day_html_snapshot(
    batch: str,
    day_url: str,
    result: FetchResult,
    pdf_links: Optional[list[str]] = None,
    language: str = "en",
    jurisdiction: Optional[str] = None,
) -> None:
    key = {"url": day_url}
    doc = {
        "url": day_url,
        "batch": batch,
        "language": language,
        "final_url": result.final_url,
        "status": result.status,
        "headers": result.headers,
        "fetched_at": result.fetched_at,
        "content": result.content,
        "parsed": False,
        "parsed_at": None,
        "parse_error": None,
    }
    if jurisdiction is not None:
        doc["jurisdiction"] = jurisdiction
    if pdf_links is not None:
        doc["pdf_links"] = pdf_links
        doc["pdf_links_updated_at"] = utc_now()

    html_col.update_one(key, {"$set": doc}, upsert=True)


def save_pdf_metadata(batch: str, day_url: str, pdf_url: str, result: FetchResult) -> None:
    key = {"batch": batch, "pdf_url": pdf_url}
    doc = {
        **key,
        "day_url": day_url,
        "final_url": result.final_url,
        "status": result.status,
        "headers": result.headers,
        "fetched_at": result.fetched_at,
    }
    pdf_col.update_one(key, {"$set": doc}, upsert=True)

# function to find the urls already scraped and avoid re-scraping them
def existing_day_urls(urls: list[str]) -> set[str]:
    docs = html_col.find({"url": {"$in": urls}}, {"_id": 0, "url": 1})
    return {doc["url"] for doc in docs}
