from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Optional

from ._render import coverage_table, last_updated_line
from ._stats import corpus_stats
from .config import (
    ALPHA_NOTICE,
    CONTACT_EMAIL,
    COVERAGE_END,
    COVERAGE_START,
    HF_DATASET_REPO,
    HF_DATASET_URL,
    REPO_README,
)

logger = logging.getLogger(__name__)


def _block(stats: Dict) -> str:
    return "\n".join(
        [
            COVERAGE_START,
            "## Dataset",
            "",
            ALPHA_NOTICE,
            "",
            last_updated_line(stats),
            "",
            "The parsed corpus is published as the Hugging Face dataset "
            f"[`{HF_DATASET_REPO}`]({HF_DATASET_URL}), built for computational legal "
            "and political research over the parliamentary record — searching for "
            "patterns, tracking how debate and policy evolve in light of case law, "
            "and assembling evidence of legislative purpose and intent. See the "
            "dataset card for fields, access, and licensing.",
            "",
            coverage_table(stats),
            "",
            f"Contact: {CONTACT_EMAIL}",
            COVERAGE_END,
        ]
    )


def generate(stats: Optional[Dict] = None, readme_path: Path = REPO_README) -> Path:
    """Refresh the coverage block in the GitHub README.

    Replaces the content between the sentinel markers. If the markers are not
    present yet, inserts the block (with markers) just after the first H1 so the
    first run is self-installing. The block always carries the last-updated date,
    so the file changes on every run even when no new sittings were added.
    """
    stats = stats or corpus_stats()
    block = _block(stats)
    text = readme_path.read_text(encoding="utf-8")

    if COVERAGE_START in text and COVERAGE_END in text:
        pre = text.split(COVERAGE_START)[0]
        post = text.split(COVERAGE_END, 1)[1]
        new = pre + block + post
    else:
        lines = text.splitlines()
        out, inserted = [], False
        for line in lines:
            out.append(line)
            if not inserted and line.startswith("# "):
                out += ["", block]
                inserted = True
        if not inserted:  # no H1 found — prepend
            out = [block, ""] + lines
        new = "\n".join(out)

    if not new.endswith("\n"):
        new += "\n"
    readme_path.write_text(new, encoding="utf-8")
    logger.info("Updated coverage block in %s", readme_path)
    return readme_path
