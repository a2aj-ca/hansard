from __future__ import annotations

from typing import Dict, Type

from .base import HansardAdapter
from .ontario import OntarioHansardAdapter


ADAPTERS: Dict[str, Type[HansardAdapter]] = {
    OntarioHansardAdapter.name: OntarioHansardAdapter,
}


def get_adapter(name: str) -> HansardAdapter:
    if name not in ADAPTERS:
        available = ", ".join(sorted(ADAPTERS)) or "(none)"
        raise ValueError(f"Unknown adapter '{name}'. Available: {available}")
    return ADAPTERS[name]()


def list_adapters() -> list[str]:
    return sorted(ADAPTERS)
