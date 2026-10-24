# Hansard Pipeline

This document explains how the Hansard scraping and parsing pipeline is organized and how it runs.

## 1. Why an adapter architecture

Different jurisdictions publish Hansards in different HTML structures, but the workflow is the same: fetch, store, mark as parsed, insert rows.

So the codebase is split into:

- **Common components** (HTTP, MongoDB, logging, schema, runner) — shared by
  all jurisdictions.
- **Adapters** — one class per jurisdiction. Each adapter knows three things:
  1. how to **discover** day URLs,
  2. how to **extract PDF links** from a day page,
  3. how to **parse** a day's HTML into rows.

Adding a new jurisdiction means writing one new file in `pipeline/adapters/` and registering it. Nothing else has to change.

---

## 2. MongoDB layout

Three collections (one DB, defaulting to `hansard`):

### `hansard-html-snapshots`

One document per **(URL)** pair. Holds the raw HTML for one day.

| Field                 | Meaning |
|-----------------------|---------|
| `url`                 | Day page URL (unique). |
| `batch`               | Run label that inserted this snapshot. |
| `language`            | `"en"` or `"fr"`. |
| `jurisdiction`        | e.g. `"ontario"`. |
| `final_url`           | URL after redirects. |
| `status`              | HTTP status code. |
| `headers`             | Response headers. |
| `fetched_at`          | UTC timestamp. |
| `content`             | Raw HTML bytes. |
| `pdf_links`           | PDFs found on the page (optional). |
| `pdf_links_updated_at`| UTC timestamp. |
| `parsed`              | `True` once successfully parsed. |
| `parsed_at`           | UTC timestamp of last parse. |
| `parse_error`         | Last parse error string, or `None`. |

### `hansard-pdf-metadata`

One document per **(batch, pdf_url)**. Records the metadata of each downloaded
PDF (currently we don't store PDF bytes — just metadata).

### `hansard-parsed-rows`

One document per **intervention** (a speaker turn or a procedural note).

Indexes:
- `hansard-html-snapshots`: unique on `url` and on `(batch, url)`.
- `hansard-pdf-metadata`: unique on `(batch, pdf_url)`.
- `hansard-parsed-rows`: unique on `(source_url, ID)`.

---

## 3. Discovery modes and `--since`

`discover(mode)` returns the list of day URLs to fetch. Each returned `DayPage`
carries the sitting `date` parsed from the URL (e.g. `.../2024-03-21/hansard`),
which the runner uses for the `--since` filter.

- **`full`** — walk every parliament/session listed on the root page, then
  every Hansard day URL listed on each session page. Use this when seeding a
  fresh database.
- **`incremental`** — only walk the "Recent House Documents" link on the root
  page and pull the day URLs from there. Then `runner.run_discover_and_fetch`
  filters to only URLs not already in `hansard-html-snapshots`, **plus** the
  `--recheck` newest known days (default 14), which are re-fetched anyway — see
  3a for why.

### 3a. Multiple sittings on one day

The House sometimes sits twice in a day. Ontario publishes each sitting as its
own transcript page:

- afternoon → `.../<date>/hansard` (the site calls it "vol. A")
- evening → `.../<date>/hansard-1` ("vol. B"), and so on for further sittings.

**Session index pages list only the vol. A page for each date.** The vol. B link
appears only in the "Hansard Transcripts vol. A / vol. B" nav *on the day page
itself*. 

So same day sittings are captured during the fetch stage, not the discover
stage: `_fetch_days` works through a queue rather than a fixed list, and after
fetching each day page it calls `adapter.extract_related_day_urls()` and appends
any same-date sitting it hasn't seen. Newly found sittings are fetched in turn,
so a third sitting linked only from the second is still picked up. same day links
are mutual (vol. B links back to vol. A), so the `seen` set is what makes the
walk terminate.

`extract_related_day_urls` keeps only links whose **date matches the current
page's date**, which is what separates true same day sessions from the "previous / next sitting day" navigation links on the same page.

---

## 4. The runner

`pipeline/runner.py` orchestrates the stages:

- `run_discover_and_fetch(adapter, batch, mode, download_pdfs, since)` —
  calls `adapter.discover()`, applies the `since` filter, applies the
  incremental "skip known URLs" filter (incremental mode only), then for each
  day URL fetches the HTML, calls `adapter.extract_pdf_links()`, saves the
  snapshot, and (optionally) fetches every PDF.
- `run_parse(adapter)` —
  finds every snapshot in this jurisdiction with `parsed != True`, calls
  `adapter.parse()`, **deletes any existing rows for that `source_url`** (so a
  re-parse can't leave orphaned rows behind when a corrected transcript yields
  fewer rows), inserts the new rows into `hansard-parsed-rows`, and marks the
  snapshot as parsed (or records the parse error).
- `run_pipeline(adapter, stage, batch, mode, download_pdfs, since)` — the public
  entry point used by the CLI, ensures indexes exist and dispatches to the
  two functions above based on `--stage`.

Re-running a stage is safe: HTML pages are saved or updated based on URL, parsed
rows for a day are deleted and re-inserted on re-parse (keyed by `(source_url,
ID)`), and each processed HTML snapshot is marked so the parser knows what has
already been handled.

---

## 5. Adding a new jurisdiction

To add e.g. Federal Hansard:

1. Create `pipeline/adapters/federal.py` with a class that subclasses
   `HansardAdapter` and sets `name`, `jurisdiction`, `chamber`,
   `supported_languages`.
2. Implement `discover(mode)`, `extract_pdf_links(html, day_url)`, and
   `parse(html, language)`.
3. Register it in `pipeline/adapters/registry.py`.
4. Run `python -m pipeline federal --mode=incremental --no-pdfs` to test.

The parsed rows will land in the same `hansard-parsed-rows` collection,
distinguishable by the `jurisdiction` field.