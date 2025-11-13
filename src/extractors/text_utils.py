from __future__ import annotations

import re
from typing import Optional

WHITESPACE_RE = re.compile(r"\s+")

def clean_text(text: str | None) -> str:
    """
    Normalize whitespace and strip leading/trailing spaces from text.
    """
    if text is None:
        return ""
    return WHITESPACE_RE.sub(" ", text).strip()

def extract_rating_from_aria(aria_label: str | None) -> Optional[float]:
    """
    Extract a float rating from an aria-label string like '4.5 star rating'.
    """
    if not aria_label:
        return None

    match = re.search(r"(\d+(\.\d+)?)", aria_label)
    if not match:
        return None

    try:
        return float(match.group(1))
    except ValueError:
        return None