from __future__ import annotations

import hashlib
import re
from typing import Optional
from urllib.parse import urlparse

# normalize whitespace
def clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


# generate a unique ID for each row based on date and sequence number
def make_id(d: Optional[str], n: int) -> Optional[str]:
    if not d:
        return None
    ymd = d.replace("-", "")
    return f"{ymd}-{n:07d}"

# Replace invalid characters with underscores
def safe_filename(s: str) -> str:
    out = []
    for c in s:
        if c.isalnum() or c in (" ", ".", "_", "-"):
            out.append(c)
        else:
            out.append("_")
    return "".join(out)

# Generate a filename from a URL
def filename_from_url(url: str) -> str:
    p = urlparse(url)
    parts = [x for x in p.path.split("/") if x]
    base = p.netloc + "__" + "__".join(parts) if parts else (p.netloc + "__download")
    #hash of full URL (includes query) for uniqueness of the file name
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
    return safe_filename(base) + "__" + h
