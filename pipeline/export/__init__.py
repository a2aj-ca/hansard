from __future__ import annotations

"""Export + publishing layer.

Turns the parsed rows in MongoDB into a Hugging Face dataset (one
``<jurisdiction>/train.parquet`` per jurisdiction plus a generated data card),
regenerates the GitHub README coverage block, and publishes both. Pure
read-from-Mongo / write-out; it never touches the scraping or parsing stages.

The end-to-end weekly job is ``python -m pipeline.export.run_weekly``.
"""
