from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Optional

from ..adapters.registry import get_adapter, list_adapters
from ..runner import run_pipeline
from . import parquet, publish_github, publish_hf, readme_github, readme_hf
from ._stats import corpus_stats

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    """Log to stdout so the cron wrapper's timestamped file captures everything
    (one real log per run, no separate file handler, no blank redirect file)."""
    logging.basicConfig(
        stream=sys.stdout,
        format=">>> %(levelname)s | %(asctime)s | %(message)s",
        level=logging.INFO,
    )
    # Quiet per-request HTTP noise from the HF upload; our own log lines remain.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.export.run_weekly",
        description=(
            "Weekly Hansard update: fetch new days, parse, export Parquet, "
            "regenerate both READMEs, and publish to Hugging Face + GitHub."
        ),
    )
    parser.add_argument(
        "--adapters", nargs="*", default=None,
        help="Adapters to update (default: all registered).",
    )
    parser.add_argument(
        "--mode", choices=["full", "incremental", "refresh"], default="incremental",
        help="Discovery mode for the fetch stage (default: incremental).",
    )
    parser.add_argument(
        "--no-fetch", action="store_true",
        help="Skip fetch/parse; only re-export and regenerate READMEs from Mongo.",
    )
    parser.add_argument("--no-pdfs", action="store_true", help="Skip PDF downloads.")
    parser.add_argument(
        "--no-publish", action="store_true",
        help="Build artifacts only; do not push to Hugging Face or GitHub.",
    )
    args = parser.parse_args(argv)

    _setup_logging()
    names = args.adapters or list_adapters()

    # 1. fetch + parse (fail-fast: never publish on a failed pull)
    if not args.no_fetch:
        for name in names:
            logger.info("=== pipeline run: %s (mode=%s) ===", name, args.mode)
            run_pipeline(
                adapter=get_adapter(name),
                stage="all",
                mode=args.mode,
                download_pdfs=not args.no_pdfs,
            )
    else:
        logger.info("Skipping fetch/parse (--no-fetch).")

    # 2. export Parquet
    paths = parquet.export_all()
    logger.info("Wrote %d Parquet file(s).", len(paths))

    # 3. regenerate both READMEs from one shared stats snapshot
    stats = corpus_stats()
    readme_hf.generate(stats)
    readme_github.generate(stats)

    # 4. publish
    if args.no_publish:
        logger.info("Built artifacts only (--no-publish); skipping HF + GitHub push.")
        return 0

    msg = f"Weekly dataset update — coverage as of {stats['last_updated']}"
    publish_hf.run(commit_message=msg)
    publish_github.run(commit_message=msg)
    logger.info("Weekly update complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
