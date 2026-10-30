# Hansard Scraper and Parser

<!-- COVERAGE:START -->
## Dataset

> **Alpha — work in progress.** This is an alpha version of a work in progress academic research project. It is likely to undergo significant revisions.

_Last updated: 2026-10-25._

The parsed corpus is published as the Hugging Face dataset [`a2aj/hansard`](https://huggingface.co/datasets/a2aj/hansard), built for computational legal and political research over the parliamentary record — searching for patterns, tracking how debate and policy evolve in light of case law, and assembling evidence of legislative purpose and intent. See the dataset card for fields, access, and licensing.

| Jurisdiction | Rows | Sitting days | Date range | Languages |
|---|---:|---:|---|---|
| Ontario — Legislative Assembly | 1,347,812 | 4,474 | 1974-03-05 → 2026-06-02 | en |
| **Total** | **1,347,812** | | | |

Example notebook for accessing the data: [`notebooks/accessing_the_data.ipynb`](notebooks/accessing_the_data.ipynb).

A project of [Access to Algorithmic Justice (A2AJ)](https://a2aj.ca). Contact: a2aj@yorku.ca
<!-- COVERAGE:END -->

A multi-jurisdiction pipeline that downloads parliamentary Hansard transcripts,
stores the raw HTML in MongoDB, and parses it into structured intervention rows
(one row per speaker turn or procedural note). Only the **Legislative Assembly
of Ontario** is implemented today, but the codebase is built around per-jurisdiction
adapters so others can be added without touching the core.

## About

This is a project of the [Access to Algorithmic Justice (A2AJ)](https://a2aj.ca), a
research project based in Toronto, Canada, co-hosted by York University's Osgoode
Hall Law School and Toronto Metropolitan University's Lincoln Alexander School of
Law, with support from the Law Foundation of Ontario. A2AJ researches and advocates
for a fairer, more accessible justice system as technology reshapes the law,
developing legal datasets, legal AI benchmarks, and open-source legal tech tools
focused on improving access to justice—especially for marginalized and low-income
communities in Canada. Ultimately, A2AJ aims to help foster a non-profit,
open-source, and rights-enhancing legal tech ecosystem in Canada.

## Why this project

Hansard—the official record of what is said in the legislature—is a uniquely rich
record of democratic deliberation: who said what, on which topic, on which day. But
as it is published online it is hard and slow to work with. The transcripts are
spread across thousands of separate day pages in shifting HTML formats, the search
tools offered upstream are limited, and there is no convenient way to query the
record as a whole or analyze it at scale.

This pipeline turns that scattered, page-by-page record into a single structured
dataset—one row per intervention, with speaker, topic, date, and text—so it can be
searched, filtered, and analyzed computationally rather than read one page at a time.
Having the full corpus in a structured form unlocks work that is otherwise
impractical: longitudinal studies of debate, tracking how issues and language evolve,
linking parliamentary discussion to legislation and case law, and building research
tools on top of the data.

It also matters for AI. Modern AI tools are far more useful, and far more accurate,
when they can engage with a complete, well-structured corpus rather than whatever
fragments a general web search happens to surface. A clean, openly available Hansard
dataset lets researchers, advocates, and the public ask questions of the
parliamentary record with AI assistance—supporting A2AJ's broader goal of an
open, rights-enhancing legal tech ecosystem.

## Pipeline stages

1. **Discover** — find the URLs of every Hansard "day page" to capture (all sessions, or only the most recent one).
2. **Fetch HTML** — download each day page and store its raw HTML. Also finds any extra sittings held the same day
3. **Fetch PDFs** — download the PDFs linked from each day page (optional).
4. **Parse** — turn each HTML snapshot into structured intervention rows.

Raw HTML, PDF metadata, and parsed rows all live in MongoDB, so re-parsing never
requires re-downloading.



## Requirements

- Python 3 and the dependencies in `requirements.txt`:
  `pip install -r requirements.txt`
- **A running MongoDB instance**, reachable at `mongodb://localhost:27017/` by
  default. MongoDB is the document database this pipeline reads from and writes to,
  so it must be installed and running before you use the tool — see the
  [MongoDB installation guide](https://www.mongodb.com/docs/manual/installation/).
  Point the pipeline at a different instance with `MONGO_URI` (see
  [Configuration](#configuration)).

## Usage

The project is a Python package, run with `python -m pipeline`:

```bash
python -m pipeline --list                                      # list available adapters
python -m pipeline ontario                                     # initial seed: all stages, full history
python -m pipeline ontario --mode=incremental                  # weekly update: only new recent days
python -m pipeline ontario --mode=refresh                      # re-fetch recent days (pull in corrections)
python -m pipeline ontario --since 2024-01-01                  # only days on or after a date
python -m pipeline ontario --stage=fetch --mode=incremental    # only new days, fetch only
python -m pipeline ontario --stage=parse                       # parse unparsed snapshots only
python -m pipeline ontario --no-pdfs                           # skip PDF downloads
python -m pipeline ontario --mode=incremental --recheck=0      # don't re-fetch recent days
```

| Flag        | Values                          | Default   | Purpose |
|-------------|---------------------------------|-----------|---------|
| `adapter`   | name (e.g. `ontario`)           | required  | Which jurisdiction to run. |
| `--list`    | —                               | —         | Print adapters and exit. |
| `--stage`   | `all`, `fetch`, `parse`         | `all`     | Which stage(s) to run. |
| `--mode`    | `full`, `incremental`, `refresh` | `full`   | Discovery strategy (see below). |
| `--since`   | `YYYY-MM-DD`                     | (none)    | Only fetch days on or after this date. |
| `--batch`   | string                          | `default` | Label stamped onto each saved snapshot. |
| `--no-pdfs` | —                               | off       | Skip PDF downloads. |
| `--recheck` | `14` | Incremental only: re-fetch the N newest known days so a late-published second sitting isn't missed. `0` disables. |

### Modes

| Mode          | Discovers          | Fetches                         | When to use |
|---------------|--------------------|---------------------------------|-------------|
| `full`        | the entire archive | all discovered days             | initial seed / full rebuild |
| `incremental` | recent days only   | only days **not** in the DB     | normal recurring update |
| `refresh`     | recent days only   | **all** recent days, re-fetching ones already saved | pull in upstream corrections to days you already have |

`--since` is a date floor applied on top of any mode (e.g. `--mode=full --since 2024-01-01`
re-fetches every archived day on/after that date). Re-fetching a day re-parses it, and a
re-parse first deletes that day's old rows, so corrected transcripts never leave stale rows behind.

### Configuration

The pipeline reads configuration from a `.env` file via `python-dotenv`. Copy the
template and fill in the values you need:

```bash
cp .env.example .env
```

Then edit `.env`. All variables are optional — with none set, the pipeline uses the
default MongoDB database `hansard` on localhost and makes direct (un-proxied) requests.

| Variable                                    | Default                      | Purpose |
|---------------------------------------------|------------------------------|---------|
| `MONGO_URI`                                 | `mongodb://localhost:27017/` | MongoDB connection URI (set for auth, TLS, replica set, or Atlas). |
| `MONGO_DB_NAME`                             | `hansard`                    | Database to read/write. |
| `PROXY`, `PROXY_USERNAME`, `PROXY_PASSWORD` | (none)                       | Optional outbound HTTP proxy (all three required to enable). |
| `REQUEST_DELAY_MIN`, `REQUEST_DELAY_JITTER` | `1.0`, `2.0`                 | Politeness delay between requests (waits min + random up to jitter seconds). |
| `HTTP_TIMEOUT`, `HTTP_RETRIES`              | `30`, `4`                    | Per-request timeout (seconds) and retry count on errors / 429 / 5xx. |

## Multiple sittings per day

When the House sits twice in a day, Ontario publishes the second sitting at
`.../<date>/hansard-1` ("vol. B"). It is linked only from the first sitting's
page, not from the session index. The fetch stage follows these same-date links
automatically. Each row records which sitting it came from (`sitting` = `A`, `B`, ...), and the sitting letter is part of the row `ID`.

To recover second sittings missed by runs made before this change, without
re-crawling, call `runner.run_backfill_sittings(adapter, batch)` from Python
(it isn't exposed on the CLI). It scans the stored snapshots for sibling links
and fetches only the pages that are missing.

See [docs/architecture.md §3a](docs/architecture.md).

## MongoDB collections

- `hansard-html-snapshots` — one document per day URL (raw HTML + fetch/parse status).
- `hansard-pdf-metadata` — metadata for downloaded PDFs.
- `hansard-parsed-rows` — parsed output, unique on `(source_url, ID)`.

### Parsed-row fields

Each document in `hansard-parsed-rows` represents one intervention (a speaker turn
or a procedural note) and has the following fields:

| Field               | Example                           | Meaning |
|---------------------|-----------------------------------|---------|
| `ID`                | `20240321A-0000042`                 | Stable per-row identifier ( `YYYYMMDD` + sitting letter + sequence). |
| `Date`              | `2024-03-21`                      | Sitting date (YYYY-MM-DD). |
| `sitting`           | `A`,  `B`                         | first, second or ... sitting of the date. |
| `jurisdiction`      | `ontario`                         | Which legislature. |
| `chamber`           | `legislative_assembly`            | Which chamber within the legislature. |
| `language`          | `en`                              | Language of the source page. |
| `OrderofBusiness`   | `STATEMENTS BY THE MINISTRY`      | High-level section heading. |
| `SubjectofBusiness` | `ONTARIO TECHNOLOGY CENTRES`      | Specific topic within the section. |
| `PersonSpeaking`    | `Hon. Mr. Walker`                 | Speaker label, or `null` for procedural and division rows. |
| `intervention_type` | `speech`, `procedural`, or `division`           | Whether the row is a speech, procedural or a division note. |
| `Intervention`      | `Mr. Speaker, I would like ...`   | The actual text of the intervention. For divisions, the voters' names joined with `; `. |
| `vote_direction`    | `aye`, `nay` on division rows     | Which side of a recorded vote (division) the row records. |
| `vote_count`        | 18                                | Count printed on the division marker, if any. |
| `voters`            | `Beer; Bradley; Brown; ...`       | Voter names on division rows, joined with `; ` in the Parquet export (a list in MongoDB); empty otherwise. |
| `source_url`        | `https://www.ola.org/.../hansard` | The day-page URL this row came from (added by the runner). |
| `upstream_license`  | (license string)                  | Upstream attribution and restriction notice for the source. |

**Known limitations**

- `vote_count` is `None` whenever the count isn't printed on the marker line.
  It is not computed from `len(voters)`, so consumers can tell "not printed"
  from "printed". Use `len(voters)` when you need a number.
- A combined tally line (`Ayes 52; nays 31.`, `Ayes, 46; nays 66.`) ends name collection
  and becomes its own `procedural` row, but its counts aren't parsed into `vote_count`.
- A paragraph consisting only of `Aye.` or `Nay.` matches the division-marker
  pattern and would wrongly start a division. This hasn't come up in practice,
  because members' spoken responses are printed with a speaker label
  ("Some hon. members: Aye").
- Divisions are only recognised in this layout. Votes reported only in prose
  ("the motion was carried on the following division: ...") are not split into
  names.

## Project structure

```
pipeline/
├── __main__.py          # CLI entry point: python -m pipeline ...
├── runner.py            # orchestrates the fetch + parse stages
├── common/              # shared HTTP, MongoDB, schema, text, logging helpers
└── adapters/            # one module per jurisdiction (base, registry, ontario)
docs/
├── architecture.md      # full design documentation
├── ontario-parsing.md   # parsing logic specefic to Ontario Hansard
```

## Adding a jurisdiction

Subclass `HansardAdapter` in a new file under `pipeline/adapters/`, implement
`discover()` / `parse()` (and optionally `extract_pdf_links()`), and register the
class in `pipeline/adapters/registry.py`. See `docs/architecture.md` §5.

## Licensing Information

The code used to create the dataset by the A2AJ and any work on the dataset
undertaken by the A2AJ is subject to an open source [MIT license](LICENSE).

Users must also comply with upstream licenses found in the `upstream_license` field
in the dataset for each document, which reflects the licenses through which the A2AJ
obtained the document. These upstream licenses may include limits on commercial use,
as well as other limitations.

The A2AJ is committed to open source methodologies, and we are actively working to
obtain more permissive licenses for this data.

## Credits

Initial code by [Yalda Radan](https://github.com/yaldaradan).

This code was developed and revised partly with the assistance of AI (Claude Code), under human
direction and review.

## Acknowledgements

This research output is supported in part by funding from the Law Foundation of
Ontario and the Social Sciences and Humanities Research Council of Canada, by
in-kind compute from the Digital Research Alliance of Canada and by administrative
support from the Centre for Refugee Studies, the Refugee Law Lab, and Osgoode Hall
Law School. We also thank the Canadian judiciary and tribunal staff who publish
decisions in open formats.
