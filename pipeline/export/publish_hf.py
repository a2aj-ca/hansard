from __future__ import annotations

import logging
import os

from huggingface_hub import HfApi

from .config import EXPORT_DIR, HF_DATASET_REPO

logger = logging.getLogger(__name__)


def run(commit_message: str = "Weekly dataset update") -> None:
    """Upload the built export folder (Parquet + data card) to the HF Hub.

    Uses upload_folder rather than datasets.push_to_hub so the hand-generated
    data card (README.md) is uploaded as-is and never overwritten. The token is
    read from HF_TOKEN (loaded from .env by pipeline/__init__.py).
    """
    token = os.getenv("HF_TOKEN")
    if not token:
        raise RuntimeError("HF_TOKEN is not set; cannot push to the Hugging Face Hub.")
    if not EXPORT_DIR.exists():
        raise RuntimeError(f"Export dir {EXPORT_DIR} does not exist; run the export first.")

    api = HfApi(token=token)
    api.create_repo(repo_id=HF_DATASET_REPO, repo_type="dataset", exist_ok=True)
    api.upload_folder(
        folder_path=str(EXPORT_DIR),
        repo_id=HF_DATASET_REPO,
        repo_type="dataset",
        commit_message=commit_message,
    )
    logger.info("Uploaded %s -> huggingface.co/datasets/%s", EXPORT_DIR, HF_DATASET_REPO)
