from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List

import pyarrow as pa
import pyarrow.parquet as pq

from ..common.mongo import parsed_col
from ..common.schema import ROW_FIELDS
from ._stats import all_jurisdictions
from .config import EXPORT_DIR

logger = logging.getLogger(__name__)

# Columns written to Parquet: the canonical row fields plus source_url (added by
# the runner). Everything is stored as nullable UTF-8 string so the schema is
# stable across rows and jurisdictions.
COLUMNS = ROW_FIELDS + ["source_url"]
SCHEMA = pa.schema([(c, pa.string()) for c in COLUMNS])
BATCH_SIZE = 5000


def _table(batch: Dict[str, list]) -> pa.Table:
    return pa.table(
        {c: pa.array(batch[c], type=pa.string()) for c in COLUMNS},
        schema=SCHEMA,
    )


def export_jurisdiction(jurisdiction: str) -> Path:
    """Write every parsed row for one jurisdiction to <export>/<j>/train.parquet.

    Full deterministic rebuild (sorted by Date, ID); overwrites any prior file.
    Streams in batches so a large corpus is never fully held in memory.
    """
    out_dir = EXPORT_DIR / jurisdiction
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "train.parquet"

    cursor = parsed_col.find({"jurisdiction": jurisdiction}, {"_id": 0}).sort(
        [("Date", 1), ("ID", 1)]
    )

    writer = pq.ParquetWriter(str(out_path), SCHEMA)
    batch: Dict[str, list] = {c: [] for c in COLUMNS}
    n = 0
    try:
        for doc in cursor:
            for c in COLUMNS:
                v = doc.get(c)
                batch[c].append(None if v is None else str(v))
            n += 1
            if len(batch[COLUMNS[0]]) >= BATCH_SIZE:
                writer.write_table(_table(batch))
                batch = {c: [] for c in COLUMNS}
        if batch[COLUMNS[0]]:
            writer.write_table(_table(batch))
    finally:
        writer.close()

    logger.info("Exported %d rows -> %s", n, out_path)
    return out_path


def export_all() -> List[Path]:
    juris = all_jurisdictions()
    logger.info("Exporting Parquet for: %s", ", ".join(juris) or "(none)")
    return [export_jurisdiction(j) for j in juris]
