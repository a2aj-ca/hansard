from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


ROW_FIELDS = [
    "ID",
    "Date",
    "sitting",
    "jurisdiction",
    "chamber",
    "language",
    "OrderofBusiness",
    "SubjectofBusiness",
    "PersonSpeaking",
    "intervention_type",
    "Intervention",
    "vote_direction",
    "vote_count",
    "voters",
    "upstream_license",
]


@dataclass
class DayPage:
    """A reference to a single Hansard day page."""
    url: str
    language: str = "en"
    date: Optional[str] = None
