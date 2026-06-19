from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


ROW_FIELDS = [
    "ID",
    "Date",
    "jurisdiction",
    "chamber",
    "language",
    "OrderofBusiness",
    "SubjectofBusiness",
    "PersonSpeaking",
    "intervention_type",
    "Intervention",
    "upstream_license",
]


@dataclass
class DayPage:
    """A reference to a single Hansard day page."""
    url: str
    language: str = "en"
    date: Optional[str] = None
