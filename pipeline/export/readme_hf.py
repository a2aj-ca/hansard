from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Optional

from ._render import coverage_table
from ._stats import corpus_stats
from .config import (
    ALPHA_NOTICE,
    CONTACT_EMAIL,
    HF_DATASET_REPO,
    HF_PRETTY_NAME,
    HF_README,
    EXPORT_DIR,
    JURISDICTION_LABELS,
)

logger = logging.getLogger(__name__)

# Prose names used in sentences (vs the table labels in JURISDICTION_LABELS).
JURISDICTION_PROSE = {
    "ontario": "the Legislative Assembly of Ontario",
}

# One row per Parquet column, in order, with type + description for the card.
FIELD_DOCS = [
    ("ID", "string", "Stable per-row identifier (sitting date + sequence number)."),
    ("Date", "string", "Sitting date (YYYY-MM-DD)."),
    ("jurisdiction", "string", "Which legislature (e.g. `ontario`)."),
    ("chamber", "string", "Chamber within the legislature (e.g. `legislative_assembly`)."),
    ("language", "string", "Language of the source page (e.g. `en`)."),
    ("OrderofBusiness", "string", "High-level section heading (the order of business)."),
    ("SubjectofBusiness", "string", "Specific topic / matter within the order of business."),
    ("PersonSpeaking", "string", "Speaker label, or empty for procedural rows."),
    ("intervention_type", "string", "`speech` (a speaker turn) or `procedural` (a procedural note)."),
    ("Intervention", "string", "The text of the intervention."),
    ("upstream_license", "string", "License / attribution terms from the source legislature."),
    ("source_url", "string", "The day-page URL this row was parsed from."),
]

LICENSE_TEXT = (
    "The code used to create the dataset by the A2AJ and any work on the dataset "
    "undertaken by the A2AJ is subject to an open source MIT license.\n\n"
    "Users must also comply with upstream licenses found in the `upstream_license` "
    "field in the dataset for each document, which reflects the licenses through "
    "which the A2AJ obtained the document. These upstream licenses may include "
    "limits on commercial use, as well as other limitations.\n\n"
    "The A2AJ is committed to open source methodologies, and we are actively "
    "working to obtain more permissive licenses for this data."
)

WARRANTIES_TEXT = (
    "While we make best efforts to ensure the completeness and accuracy of the "
    "dataset, we provide no warranties regarding completeness or accuracy. The "
    "data were collected through automated processes and may contain errors. "
    "Always verify data against the official source."
)

ACKNOWLEDGEMENTS_TEXT = (
    "This research output is supported in part by funding from the Law Foundation "
    "of Ontario and the Social Sciences and Humanities Research Council of Canada, "
    "by in-kind compute from the Digital Research Alliance of Canada and by "
    "administrative support from the Centre for Refugee Studies, the Refugee Law "
    "Lab, and Osgoode Hall Law School."
)


def _size_category(n: int) -> str:
    for limit, label in [
        (1_000, "n<1K"),
        (10_000, "1K<n<10K"),
        (100_000, "10K<n<100K"),
        (1_000_000, "100K<n<1M"),
        (10_000_000, "1M<n<10M"),
        (100_000_000, "10M<n<100M"),
    ]:
        if n < limit:
            return label
    return "100M<n<1B"


def _prose_jurisdiction_list(stats: Dict) -> str:
    names = [JURISDICTION_PROSE.get(j, JURISDICTION_LABELS.get(j, j)) for j in stats["jurisdictions"]]
    if not names:
        return "Canadian legislatures"
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + f", and {names[-1]}"


def _frontmatter(stats: Dict) -> str:
    langs = stats["languages"] or ["en"]
    lines = ["---", "license: mit", "language:"]
    lines += [f"- {l}" for l in langs]
    lines.append(f"pretty_name: {HF_PRETTY_NAME}")
    lines.append("tags:")
    lines += [
        f"- {t}"
        for t in [
            "legal",
            "law",
            "legislation",
            "hansard",
            "parliament",
            "canada",
            "politics",
            "legal-research",
            "computational-social-science",
        ]
    ]
    lines += ["size_categories:", f"- {_size_category(stats['total_rows'])}"]
    lines.append("configs:")
    for j in stats["jurisdictions"]:
        lines += [
            f"- config_name: {j}",
            "  data_files:",
            "  - split: train",
            f"    path: {j}/train.parquet",
        ]
    lines.append("---")
    return "\n".join(lines)


def _loading_section(stats: Dict) -> str:
    example = stats["jurisdictions"][0] if stats["jurisdictions"] else "ontario"
    configs = ", ".join(f"`{j}`" for j in stats["jurisdictions"]) or "`ontario`"
    return "\n".join(
        [
            "## Data Loading",
            "",
            f"Each jurisdiction is a separate config ({configs}), each with a single "
            "`train` split.",
            "",
            "```python",
            "from datasets import load_dataset",
            "",
            "# load one jurisdiction",
            f'rows = load_dataset("{HF_DATASET_REPO}", "{example}", split="train")',
            "df = rows.to_pandas()",
            "df.head()",
            "```",
            "",
            "The dataset is also offered in Parquet format for fast local use. Files "
            "are in subfolders named after each jurisdiction:",
            "",
            "```python",
            "import pandas as pd",
            "",
            f'df = pd.read_parquet("hf://datasets/{HF_DATASET_REPO}/{example}/train.parquet")',
            "```",
        ]
    )


def _fields_section() -> str:
    lines = [
        "## Data Fields",
        "",
        "One row per intervention (a speaker turn or a procedural note).",
        "",
        "| Field | Type | Description |",
        "|---|---|---|",
    ]
    lines += [f"| `{n}` | {t} | {d} |" for n, t, d in FIELD_DOCS]
    lines += [
        "",
        "Missing values are represented as empty strings or nulls; in particular "
        "`PersonSpeaking` is empty for procedural rows.",
    ]
    return "\n".join(lines)


def _body(stats: Dict) -> str:
    juris = _prose_jurisdiction_list(stats)
    sections = [
        f"# {HF_PRETTY_NAME}",
        "",
        ALPHA_NOTICE,
        "",
        f"Last updated: {stats['last_updated']}",
        "",
        "Maintainer: Access to Algorithmic Justice (A2AJ)",
        "",
        "## Dataset Summary",
        "",
        "The A2AJ Canadian Hansard dataset provides bulk, open-access parliamentary "
        "Hansard transcripts — the official record of debate — for Canadian "
        "legislatures, parsed into structured rows with one row per intervention "
        f"(a speaker turn or a procedural note). It currently covers {juris}.",
        "",
        "The dataset is built for computational legal and political research: "
        "programmatically searching the parliamentary record for patterns; tracking "
        "how debate, policy, and language evolve over time and in response to case "
        "law and policy developments; assembling evidence about the purpose and "
        "intent behind legislation and regulations for statutory interpretation; and "
        "linking parliamentary discussion to legislation and case law. It is also "
        "intended to support legal-tech prototyping and language-model research in "
        "the public interest — especially work that advances access to justice for "
        "marginalised and low-income communities.",
        "",
        "A2AJ is a research project co-hosted by York University's Osgoode Hall Law "
        "School and Toronto Metropolitan University's Lincoln Alexander School of Law.",
        "",
        "## Dataset Structure",
        "",
        coverage_table(stats),
        "",
        "_Counts are approximate and will drift as the dataset is updated._",
        "",
        _fields_section(),
        "",
        "## Data Languages",
        "",
        "Where available, rows record the language of the source page. Coverage is "
        "currently English; bilingual jurisdictions may add French in future.",
        "",
        "## Data Splits",
        "",
        "All rows for a jurisdiction are provided in a single `train` split.",
        "",
        _loading_section(stats),
        "",
        "## Dataset Creation",
        "",
        "### Curation Rationale",
        "",
        "Building on A2AJ's broader open legal-data programme, we collect and share "
        "the Canadian parliamentary record to democratise access to it, to enable "
        "large-scale empirical research, and to support responsible AI development "
        "for the justice and democratic sectors. We scrape data only where permitted "
        "by the terms of service of the websites that host it.",
        "",
        "### Source Data & Normalisation",
        "",
        "Transcripts are scraped from the official legislature websites and parsed "
        "from HTML into structured rows. Text is stored with minimal normalisation "
        "(HTML → plain text, whitespace cleanup). Headings are mapped to "
        "`OrderofBusiness` / `SubjectofBusiness`, and each speaker turn or procedural "
        "note becomes one row.",
        "",
        "### Non-Official Versions & Disclaimer",
        "",
        "The texts here are unofficial copies. For authoritative versions, consult "
        "the source URL in `source_url`.",
        "",
        "### Non-Affiliation / Endorsement",
        "",
        "A2AJ and the production of this dataset are not affiliated with, nor "
        "endorsed by, the listed legislatures or governments.",
        "",
        "## Considerations for Using the Data",
        "",
        "- **Social Impact.** Open parliamentary data reduces information asymmetries "
        "but can also be misused. We encourage downstream users to ensure derivative "
        "tools advance — rather than undermine — access to justice and democratic "
        "accountability.",
        "- **Bias & Representativeness.** Hansard reflects what was said in the "
        "chamber under particular editorial and procedural conventions; it is not a "
        "neutral or complete record of all political activity.",
        "- **Limitations.** Parsing is automated and approximate. HTML formats differ "
        "across parliaments, the `speech` / `procedural` classification is "
        "heuristic, and attached PDFs are not parsed (only the HTML record). Verify "
        "against the official source before relying on any row.",
        "",
        "## Licensing Information",
        "",
        LICENSE_TEXT,
        "",
        "## Warranties / Representations",
        "",
        WARRANTIES_TEXT,
        "",
        "## Dataset Curators",
        "",
        "- Access to Algorithmic Justice (A2AJ)",
        f"- Contact: {CONTACT_EMAIL}",
        "",
        "## Acknowledgements",
        "",
        ACKNOWLEDGEMENTS_TEXT,
    ]
    return "\n".join(sections)


def generate(stats: Optional[Dict] = None) -> Path:
    """Write the Hugging Face data card to <export>/README.md."""
    stats = stats or corpus_stats()
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    content = _frontmatter(stats) + "\n\n" + _body(stats) + "\n"
    HF_README.write_text(content, encoding="utf-8")
    logger.info("Wrote HF data card -> %s", HF_README)
    return HF_README
