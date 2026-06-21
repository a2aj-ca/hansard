from __future__ import annotations

from typing import Dict, List

from ..common.http import utc_now
from ..common.mongo import parsed_col


def all_jurisdictions() -> List[str]:
    """Every jurisdiction that currently has parsed rows, sorted."""
    return sorted(j for j in parsed_col.distinct("jurisdiction") if j)


def compute_stats(jurisdiction: str) -> Dict:
    """Coverage stats for one jurisdiction, read from the parsed-rows collection."""
    match = {"jurisdiction": jurisdiction}

    # Coverage range over rows with a usable (string) Date, so a stray null
    # cannot drag $min down to null.
    agg = list(
        parsed_col.aggregate(
            [
                {"$match": {**match, "Date": {"$type": "string"}}},
                {
                    "$group": {
                        "_id": None,
                        "dated_rows": {"$sum": 1},
                        "coverage_start": {"$min": "$Date"},
                        "coverage_end": {"$max": "$Date"},
                    }
                },
            ]
        )
    )
    base = agg[0] if agg else {}

    by_type = {
        (r["_id"] or "unknown"): r["n"]
        for r in parsed_col.aggregate(
            [
                {"$match": match},
                {"$group": {"_id": "$intervention_type", "n": {"$sum": 1}}},
            ]
        )
    }

    sitting_days = len([d for d in parsed_col.distinct("Date", match) if d])
    languages = sorted(lang for lang in parsed_col.distinct("language", match) if lang)

    return {
        "jurisdiction": jurisdiction,
        "row_count": parsed_col.count_documents(match),
        "dated_row_count": base.get("dated_rows", 0),
        "coverage_start": base.get("coverage_start"),
        "coverage_end": base.get("coverage_end"),
        "sitting_days": sitting_days,
        "by_type": by_type,
        "languages": languages,
    }


def corpus_stats() -> Dict:
    """A single snapshot of stats for every jurisdiction, shared by both READMEs."""
    juris = all_jurisdictions()
    per = {j: compute_stats(j) for j in juris}
    now = utc_now()
    return {
        "generated_at": now,
        "last_updated": now.strftime("%Y-%m-%d"),
        "jurisdictions": juris,
        "per_jurisdiction": per,
        "total_rows": sum(s["row_count"] for s in per.values()),
        "languages": sorted({lang for s in per.values() for lang in s["languages"]}),
    }
