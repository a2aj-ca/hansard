from __future__ import annotations

import logging
from pathlib import Path


def setup_logging(name: str) -> logging.Logger:
    log_path = Path("LOGS") / f"{name}.log"
    log_path.parent.mkdir(exist_ok=True)

    if not logging.getLogger().handlers:
        logging.basicConfig(
            filename=str(log_path),
            filemode="a",
            format=">>> %(levelname)s | %(asctime)s | %(message)s",
            level=logging.INFO,
        )
    return logging.getLogger(name)
