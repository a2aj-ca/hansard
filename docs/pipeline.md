# Hansard Pipeline

This document explains how the Hansard scraping and parsing pipeline is organized and how it runs.

## 1. What this pipeline does

The pipeline takes parliamentary Hansard transcripts published online by a
legislature (currently the **Legislative Assembly of Ontario**) and turns them
into structured rows that downstream analysis can use.

There are four logical stages:

1. **Discover** — find the URLs of every Hansard "day page" we want to capture.
2. **Fetch HTML** — download each day page and store its raw HTML.
3. **Fetch PDFs** — download the PDFs linked from each day page (optional).
4. **Parse** — turn each HTML snapshot into a list of structured intervention rows (one row per speaker turn or procedural note).

All raw HTML, all PDF metadata, and all parsed rows are stored in **MongoDB** so that re-parsing never requires re-downloading.

---

## 2. Why an adapter architecture

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

## 3. Folder structure

pipeline/
├── __init__.py
├── __main__.py              # CLI entry point: `python -m pipeline ...`
├── runner.py                # Orchestrates fetch + parse stages
├── common/
│   ├── http.py              # fetch(), retries, proxies, FetchResult
│   ├── mongo.py             # MongoDB client, collections, save helpers
│   ├── schema.py            # ROW_FIELDS list, DayPage dataclass
│   ├── text.py              # clean_text(), make_id(), helpers
│   └── logging_setup.py     # per-adapter log file setup
└── adapters/
    ├── base.py              # HansardAdapter abstract base class
    ├── registry.py          # name → adapter class lookup
    └── ontario.py           # Ontario implementation

---

## 4. How a user runs the pipeline

The pipeline is a Python package, so it runs with `python -m pipeline`.

```bash
# list available adapters
python -m pipeline --list

# initial seed: all stages (discover + fetch HTML + fetch PDFs + parse), full history
python -m pipeline ontario

# recurring update: only the most recent session's new days
python -m pipeline ontario --mode=incremental

# re-fetch the recent days even if already saved (pull in upstream corrections)
python -m pipeline ontario --mode=refresh

# restrict any run to days on or after a date
python -m pipeline ontario --since 2024-01-01

# only fetch (no parsing); only the most recent session's new days
python -m pipeline ontario --stage=fetch --mode=incremental

# parse whatever HTML snapshots are already in Mongo but not yet parsed
python -m pipeline ontario --stage=parse

# skip PDF downloads
python -m pipeline ontario --no-pdfs

```

### CLI flags

| Flag           | Values                            | Default     | Purpose |
|----------------|-----------------------------------|-------------|---------|
| `adapter`      | name (e.g. `ontario`)             | required    | Which jurisdiction to run. |
| `--list`       | —                                 | —           | Print adapters and exit. |
| `--stage`      | `all`, `fetch`, `parse`           | `all`       | Which pipeline stage(s) to run. |
| `--mode`       | `full`, `incremental`, `refresh`  | `full`      | Discovery strategy (see §8). |
| `--since`      | `YYYY-MM-DD`                      | (none)      | Only fetch days on or after this date (validated for format). |
| `--batch`      | string                            | `default`   | Label stamped onto each saved snapshot for traceability. |
| `--no-pdfs`    | —                                 | off         | Skip PDF downloads. |

### Configuration / `.env`

Copy the template and fill in the values you need:

```bash
cp .env.example .env
```

All variables are optional — with none set, the pipeline uses the default MongoDB
database `hansard` on localhost and makes direct (un-proxied) requests.

### Environment variables

| Variable               | Default                      | Purpose |
|------------------------|------------------------------|---------|
| `MONGO_URI`            | `mongodb://localhost:27017/` | MongoDB connection URI (set for auth, TLS, replica set, or Atlas). |
| `MONGO_DB_NAME`        | `hansard`                    | Which Mongo database to read/write. |
| `PROXY`                | (none)                       | Optional proxy host (e.g. `host:port`) for outbound fetches. |
| `PROXY_USERNAME`       | (none)                       | Proxy username. |
| `PROXY_PASSWORD`       | (none)                       | Proxy password. |
| `REQUEST_DELAY_MIN`    | `1.0`                        | Minimum delay (seconds) before each request. |
| `REQUEST_DELAY_JITTER` | `2.0`                        | Extra random delay (0..jitter seconds) added on top. |
| `HTTP_TIMEOUT`         | `30`                         | Per-request timeout in seconds. |
| `HTTP_RETRIES`         | `4`                          | Retry attempts on network errors / 429 / 5xx. |

`.env` is loaded once in `pipeline/__init__.py` (via `python-dotenv`) **before**
any module reads its configuration, so values in `.env` reliably apply even though
`common/mongo.py` builds its client and `common/http.py` reads its tunables at
import time.

`build_proxies()` in `common/http.py` reads the proxy settings at fetch time. A
proxy is only used when **all three** of `PROXY`, `PROXY_USERNAME`, and
`PROXY_PASSWORD` are set; otherwise fetches go out directly. The MongoDB URI and
database, the request-delay knobs, and the HTTP timeout/retry budget are read at
import time and default to the values above.

---

## 5. MongoDB layout

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
This is the canonical output of the pipeline. See section 6.

Indexes:
- `hansard-html-snapshots`: unique on `url` and on `(batch, url)`.
- `hansard-pdf-metadata`: unique on `(batch, pdf_url)`.
- `hansard-parsed-rows`: unique on `(source_url, ID)`.

---

## 6. The parsed row schema

Defined in `pipeline/common/schema.py` as `ROW_FIELDS`.

| Field               | Example                         | Meaning |
|---------------------|---------------------------------|---------|
| `ID`                | `2024-03-21__042`               | Stable per-row identifier (date + sequence). |
| `Date`              | `2024-03-21`                    | Sitting date (YYYY-MM-DD). |
| `jurisdiction`      | `ontario`                       | Which legislature. |
| `chamber`           | `legislative_assembly`          | Which chamber within the legislature. |
| `language`          | `en`                            | Language of the source page. |
| `OrderofBusiness`   | `STATEMENTS BY THE MINISTRY`    | High-level section heading. |
| `SubjectofBusiness` | `ONTARIO TECHNOLOGY CENTRES`    | Specific topic within the section. |
| `PersonSpeaking`    | `Hon. Mr. Walker`               | Speaker label, or `None` for procedural rows. |
| `intervention_type` | `speech` or `procedural`        | Whether this row is a speech or a procedure note. |
| `Intervention`      | `Mr. Speaker, I would like ...` | The actual text. |
| `source_url`        | `https://www.ola.org/.../hansard` | The day URL this row came from (added by the runner). |
| `upstream_license`  | (license string)                | non-commercial-use notice. |

`upstream_license` for Ontario is:

> See upstream license, including non-commercial use and other restrictions:
> https://perma.cc/D5TN-9RX6. Note: This is an unofficial reproduction of
> materials made available by the Legislative Assembly of Ontario, without
> endorsement by or affiliation with the Legislative Assembly of Ontario.

---

## 7. How parsing works (Ontario)

Ontario publishes Hansards in two distinct HTML formats across the years.

### 7a. Modern format (most parliaments)

- `<h2>` → `OrderofBusiness`.
- `<h3>` / `<h4>` → `SubjectofBusiness`.
- `<p class="speakerStart">` containing `<strong>Speaker Name:</strong> ...`
  starts a new speaker turn.
- `<p class="Procedure">` is a procedural note.
- Other `<p>` tags continue the current speaker.

### 7b. Older format (32nd, 37th, 39th parliaments observed so far)

These files don't use `<h2>`/`<h3>`. Instead they style headings as paragraphs
with a `class` attribute that mimics table cells:

- `<p class="th">` → `OrderofBusiness` (high-level section, e.g. "STATEMENT
  BY THE MINISTRY").
- `<p class="td">` → `SubjectofBusiness` (specific topic, e.g. "ONTARIO
  TECHNOLOGY CENTRES").
- Speakers are still marked by `<strong>Name:</strong>` inside a paragraph.

The parser handles both formats in one pass — it checks paragraph class names
first, falls back to `<h2>`/`<h3>` headings, and finally treats everything
else as paragraph body. The mapping is applied to every document, no matter what parliament number it comes from. the class is a sufficient signal.

### Procedural vs speech

A row is `intervention_type="procedural"` (and `PersonSpeaking=None`) when
either:
- the paragraph is `class="Procedure"`, or
- there is no current speaker and the text matches the procedural-language
  regex (`Interjections`, `Applause`, `The Speaker:`, `Pursuant to ...`, etc.).

Otherwise it's `intervention_type="speech"` with the speaker name in
`PersonSpeaking`.

---

## 8. Discovery modes and `--since`

`discover(mode)` returns the list of day URLs to fetch. Each returned `DayPage`
carries the sitting `date` parsed from the URL (e.g. `.../2024-03-21/hansard`),
which the runner uses for the `--since` filter.

- **`full`** — walk every parliament/session listed on the root page, then
  every Hansard day URL listed on each session page. Use this when seeding a
  fresh database.
- **`incremental`** — only walk the "Recent House Documents" link on the root
  page and pull the day URLs from there. Then `runner.run_discover_and_fetch`
  filters to only URLs **not already** in `hansard-html-snapshots`, so only
  genuinely new days are fetched. Use this for recurring updates.
- **`refresh`** — same recent-only discovery scope as `incremental`, but the
  runner **skips** the "already in DB" filter, so days already saved are
  re-fetched. Because re-fetching a snapshot resets its `parsed` flag, those
  days are then re-parsed — this is how upstream corrections to days you already
  have get picked up.

Independently of mode, `--since YYYY-MM-DD` drops any discovered day whose date
is before the given date (days with no parseable date are kept, never silently
dropped). This composes with any mode — e.g. `--mode=full --since 2024-01-01`
re-fetches every archived day on/after that date.

---

## 9. The runner

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

## 10. Adding a new jurisdiction

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

---

## 11. License and attribution

The pipeline fetches publicly available Hansard pages. Each parsed row carries
an `upstream_license` field with the upstream attribution / restriction
notice for that jurisdiction.
