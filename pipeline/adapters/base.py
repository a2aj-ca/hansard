from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from ..common.schema import DayPage


class HansardAdapter(ABC):
    """Base class for jurisdiction-specific Hansard pipeline adapters."""

    name: str                         # short identifier, e.g. "ontario"
    jurisdiction: str                 # e.g. "ontario"
    chamber: str                      # e.g. "legislative_assembly"
    supported_languages: List[str]    # e.g. ["en"]

    @abstractmethod
    def discover(self, mode: str = "full") -> List[DayPage]:
        """Return the list of Hansard day URLs to fetch.

        mode="full"        — full historical discovery
        mode="incremental" — only the most recent session's days
        """

    @abstractmethod
    def parse(self, html: bytes, language: str = "en") -> List[Dict[str, Optional[str]]]:
        """Parse a day's HTML into normalized intervention rows."""

    def extract_pdf_links(self, html: bytes, day_url: str) -> List[str]:
        """Optional: extract PDF links for a given day page. Default: none."""
        return []
