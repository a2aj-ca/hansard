# Publishing: Parquet export, READMEs, and the weekly cron

This describes the export/publishing layer (`pipeline/export/`) that turns the
parsed rows in MongoDB into the Hugging Face dataset
[`a2aj/hansard`](https://huggingface.co/datasets/a2aj/hansard) and keeps the
GitHub README's coverage block current. It assumes the scraping/parsing pipeline
(`python -m pipeline ontario`) has already populated Mongo — see `README.md`.

## What it does

`python -m pipeline.export.run_weekly` runs, in order:

1. **Fetch + parse** new days (`--mode=incremental` by default) for every
   registered adapter — fail-fast, so nothing is published if a pull fails.
2. **Export Parquet** — one `hf_export/<jurisdiction>/train.parquet` (single
   `train` split) per jurisdiction, a full deterministic rebuild from Mongo.
3. **Regenerate both READMEs** from one shared stats snapshot:
   - `hf_export/README.md` — the Hugging Face **data card** (YAML frontmatter +
     coverage + schema + access examples + licensing), data-focused.
   - the repo `README.md` — a coverage block (with a **Last updated** date)
     injected between `<!-- COVERAGE:START -->` / `<!-- COVERAGE:END -->`.
4. **Publish** — `upload_folder` to the HF dataset repo (not `push_to_hub`, so
   the data card is never overwritten), then commit + push `README.md` to GitHub.

The repo README is committed **every run**, even with no new sittings: the
"Last updated" date is itself the signal that the corpus was checked.

### Useful flags

```bash
python -m pipeline.export.run_weekly --no-publish   # build artifacts only, inspect hf_export/
python -m pipeline.export.run_weekly --no-fetch     # re-export + regenerate from existing Mongo
python -m pipeline.export.run_weekly --mode=full    # re-fetch full history before exporting
```

`hf_export/` is gitignored (the Parquet is too large for the code repo).

## Dependencies

Beyond the core pipeline deps, the export layer needs `pyarrow` and
`huggingface_hub` (both in `requirements.txt`): `pip install -r requirements.txt`.

## Configuration (`.env`)

All of the following are optional except the secrets needed for publishing. They
are read from `.env` (loaded by `pipeline/__init__.py`):

| Variable | Default | Purpose |
|---|---|---|
| `HF_TOKEN` | (none) | **Required to push to HF.** Write token, see below. |
| `GIT_SSH_COMMAND` | (none) | **Required to push to GitHub from cron.** Points git at the deploy key, see below. |
| `HF_DATASET_REPO` | `a2aj/hansard` | Target HF dataset repo. |
| `GIT_PUSH_URL` | `git@github.com:a2aj-ca/hansard.git` | SSH push URL (so the deploy key is used; `origin` is HTTPS). |
| `GIT_BRANCH` | `main` | Branch to push the README to. |
| `GIT_AUTHOR_NAME` | `Sean Rehaag` | Name on the automated commit. |
| `GIT_AUTHOR_EMAIL` | `srehaag@osgoode.yorku.ca` | Email on the automated commit. |
| `HF_EXPORT_DIR` | `<repo>/hf_export` | Where Parquet + the data card are built. |

## Hugging Face token

1. Go to <https://huggingface.co/settings/tokens> → **Create new token** →
   **Fine-grained**.
2. Scope it to the **`a2aj/hansard` dataset repo** with **Write** access to
   contents (least privilege; a default *read* token will 403 on upload).
3. Add it to `.env`:

   ```
   HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxx
   ```

The library reads `HF_TOKEN` automatically — no `huggingface-cli login` needed.

## GitHub deploy key (SSH)

A repo-scoped deploy key lets the cron job push the README without your personal
credentials and without an SSH agent.

1. **Generate a passphraseless key on the server** (cron has no agent to unlock a
   passphrase):

   ```bash
   ssh-keygen -t ed25519 -f /home/sr/.ssh/hansard_deploy -N "" -C "hansard-cron"
   ```

2. **Add the public key to the repo**: GitHub → `a2aj-ca/hansard` → Settings →
   Deploy keys → **Add deploy key** → paste the contents of
   `/home/sr/.ssh/hansard_deploy.pub` → **check "Allow write access"**.

3. **Point git at the key** by adding this to `.env` (the Python code passes the
   environment through to `git`):

   ```
   GIT_SSH_COMMAND=ssh -i /home/sr/.ssh/hansard_deploy -o IdentitiesOnly=yes
   ```

4. **Verify** once, manually:

   ```bash
   GIT_SSH_COMMAND="ssh -i /home/sr/.ssh/hansard_deploy -o IdentitiesOnly=yes" \
     ssh -T git@github.com   # expect a "successfully authenticated" message
   ```

The push uses `GIT_PUSH_URL` (the SSH URL), so `origin` can stay HTTPS.

## Installing the cron job

1. Make the wrapper executable: `chmod +x scripts/weekly_update.sh`.
2. Dry-run it once by hand and check the log under `LOGS/`:

   ```bash
   ./scripts/weekly_update.sh --no-publish
   ```

3. Add the schedule with `crontab -e` (see `scripts/crontab.example`):

   ```
   30 3 * * 1 /home/sr/a2aj-hansard/scripts/weekly_update.sh
   ```

The wrapper sets the working directory, selects the venv interpreter, takes a
single-run lock (`flock`), and writes a timestamped log to `LOGS/`. Everything
else (including `.env` loading) happens in Python.

### Cron gotchas (already handled, but worth knowing)

- Cron has a near-empty environment and **no SSH agent** — hence the
  passphraseless deploy key + `GIT_SSH_COMMAND`, and secrets in `.env` (loaded by
  the code) rather than the crontab.
- The wrapper uses absolute paths and `.venv/bin/python` directly, so no shell
  profile or `activate` is required.

## Monitoring

For an unattended weekly job, add a dead-man's-switch (e.g. healthchecks.io): a
job that silently stops running is otherwise invisible until the data goes stale.
Each run writes one log: `LOGS/weekly_<timestamp>.log` (the Python run logs to
stdout, which the wrapper redirects there).
