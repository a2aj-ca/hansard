from __future__ import annotations

import argparse
import re
import sys

from .adapters.registry import get_adapter, list_adapters
from .common.logging_setup import setup_logging
from .runner import run_pipeline


def main(argv: list[str] | None = None) -> int:
    #entry point that runs when someone types python -m pipeline
    parser = argparse.ArgumentParser(
        prog="python -m pipeline",
        description="Hansard multi-jurisdiction pipeline.",
    )
    # Which jurisdiction to run (e.g. "ontario").
    parser.add_argument(
        "adapter",
        nargs="?",
        help=f"Adapter name. Available: {', '.join(list_adapters())}",
    )
    # Print available adapters and exit without running anything.
    parser.add_argument("--list", action="store_true", help="List available adapters and exit.")
    # Pick which pipeline stage to run.
    parser.add_argument(
        "--stage",
        choices=["all", "fetch", "parse"],
        default="all",
        help="Which pipeline stage to run (default: all).",
    )
    # Discovery strategy: full history, only new recent days, or re-fetch recent days.
    parser.add_argument(
        "--mode",
        choices=["full", "incremental", "refresh"],
        default="full",
        help=(
            "Discovery mode: full historical scan, incremental (new recent days "
            "only), or refresh (re-fetch recent days, including ones already saved)."
        ),
    )
    # Optional date floor (YYYY-MM-DD): only fetch sitting days on or after this date.
    parser.add_argument(
        "--since",
        default=None,
        help="Only fetch days on or after this date (YYYY-MM-DD).",
    )
    # Label attached onto each Mongo snapshot
    parser.add_argument("--batch", default="default", help="Batch label stored on each snapshot.")
    # Skip PDF downloads (HTML snapshots only).
    parser.add_argument("--no-pdfs", action="store_true", help="Skip PDF downloads.")

    args = parser.parse_args(argv)

    if args.list:
        for name in list_adapters():
            print(name)
        return 0

    if not args.adapter:
        parser.error("adapter name is required (or pass --list)")

    if args.since and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.since):
        parser.error("--since must be in YYYY-MM-DD format")

    # .env is loaded in pipeline/__init__.py, before any module reads its config.
    setup_logging(f"pipeline_{args.adapter}")

    adapter = get_adapter(args.adapter)
    run_pipeline(
        adapter=adapter,
        stage=args.stage,
        batch=args.batch,
        mode=args.mode,
        download_pdfs=not args.no_pdfs,
        since=args.since,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
