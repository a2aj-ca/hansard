from __future__ import annotations

from typing import Dict

from .config import JURISDICTION_LABELS


def coverage_table(stats: Dict) -> str:
    """A markdown table of per-jurisdiction coverage, with a totals row."""
    lines = [
        "| Jurisdiction | Rows | Sitting days | Date range | Languages |",
        "|---|---:|---:|---|---|",
    ]
    for j in stats["jurisdictions"]:
        s = stats["per_jurisdiction"][j]
        label = JURISDICTION_LABELS.get(j, j)
        start, end = s["coverage_start"], s["coverage_end"]
        rng = f"{start} → {end}" if start and end else "—"
        langs = ", ".join(s["languages"]) or "—"
        lines.append(
            f"| {label} | {s['row_count']:,} | {s['sitting_days']:,} | {rng} | {langs} |"
        )
    lines.append(f"| **Total** | **{stats['total_rows']:,}** | | | |")
    return "\n".join(lines)


def last_updated_line(stats: Dict) -> str:
    return f"_Last updated: {stats['last_updated']}._"
