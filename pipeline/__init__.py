from __future__ import annotations

# Load .env as early as possible — before any submodule (e.g. common.mongo,
# common.http) reads environment variables or builds clients at import time.
from dotenv import load_dotenv

load_dotenv(override=True)
