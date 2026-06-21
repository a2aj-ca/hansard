from __future__ import annotations

import os
from pathlib import Path

# Repo root = two levels up from this file (pipeline/export/config.py).
REPO_ROOT = Path(__file__).resolve().parents[2]

# Where Parquet files + the generated HF data card are built. Gitignored
# (too large for the code repo). Override with HF_EXPORT_DIR.
EXPORT_DIR = Path(os.getenv("HF_EXPORT_DIR", str(REPO_ROOT / "hf_export")))

# Hugging Face dataset repo (namespace/name).
HF_DATASET_REPO = os.getenv("HF_DATASET_REPO", "a2aj/hansard")
HF_DATASET_URL = f"https://huggingface.co/datasets/{HF_DATASET_REPO}"

# GitHub push target. Defaults to the SSH URL so an unattended cron run uses the
# deploy key (origin is HTTPS, which would prompt for credentials). Override with
# GIT_PUSH_URL / GIT_BRANCH.
GIT_PUSH_URL = os.getenv("GIT_PUSH_URL", "git@github.com:a2aj-ca/hansard.git")
GIT_BRANCH = os.getenv("GIT_BRANCH", "main")

# Identity stamped on the automated README commit.
GIT_AUTHOR_NAME = os.getenv("GIT_AUTHOR_NAME", "Sean Rehaag")
GIT_AUTHOR_EMAIL = os.getenv("GIT_AUTHOR_EMAIL", "srehaag@osgoode.yorku.ca")

# Files the generators write to.
REPO_README = REPO_ROOT / "README.md"
HF_README = EXPORT_DIR / "README.md"

# Sentinel markers delimiting the auto-generated coverage block in the GitHub
# README. The generator replaces everything between them and inserts them after
# the first H1 if they are not present yet.
COVERAGE_START = "<!-- COVERAGE:START -->"
COVERAGE_END = "<!-- COVERAGE:END -->"

# Dataset card metadata.
HF_PRETTY_NAME = "Canadian Hansard (A2AJ)"

# Shown prominently on both the data card and the GitHub README.
ALPHA_NOTICE = (
    "> **Alpha — work in progress.** This is an alpha version of a work in "
    "progress academic research project. It is likely to undergo significant "
    "revisions."
)

# Contact, used on both READMEs.
CONTACT_EMAIL = "a2aj@yorku.ca"

# Human-friendly jurisdiction display names (falls back to the raw key).
JURISDICTION_LABELS = {
    "ontario": "Ontario — Legislative Assembly",
}
