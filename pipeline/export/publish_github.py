from __future__ import annotations

import logging
import subprocess

from .config import (
    GIT_AUTHOR_EMAIL,
    GIT_AUTHOR_NAME,
    GIT_BRANCH,
    GIT_PUSH_URL,
    REPO_README,
    REPO_ROOT,
)

logger = logging.getLogger(__name__)


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(REPO_ROOT),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def run(commit_message: str) -> bool:
    """Commit the regenerated README and push it over SSH (deploy key).

    Stages only README.md, so unrelated working-tree state is untouched. Pushes
    to GIT_PUSH_URL (an SSH URL) so the cron job authenticates with the deploy
    key via GIT_SSH_COMMAND rather than the HTTPS origin. Returns True if a
    commit was pushed, False if there was nothing to commit.
    """
    rel_readme = str(REPO_README.relative_to(REPO_ROOT))
    _git("add", rel_readme)

    # diff --cached --quiet exits 0 when nothing is staged.
    nothing_staged = (
        subprocess.run(
            ["git", "diff", "--cached", "--quiet"], cwd=str(REPO_ROOT)
        ).returncode
        == 0
    )
    if nothing_staged:
        logger.info("No README changes to commit.")
        return False

    _git(
        "-c", f"user.name={GIT_AUTHOR_NAME}",
        "-c", f"user.email={GIT_AUTHOR_EMAIL}",
        "commit", "-m", commit_message,
    )
    _git("push", GIT_PUSH_URL, f"HEAD:{GIT_BRANCH}")
    logger.info("Pushed README update to %s (%s)", GIT_PUSH_URL, GIT_BRANCH)
    return True
