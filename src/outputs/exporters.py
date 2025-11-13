from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable, List, Mapping

logger = logging.getLogger("yelp_scraper.exporters")

def _ensure_serializable(record: Any) -> Any:
    """
    Best-effort conversion of complex objects to JSON-serializable structures.
    """
    if isinstance(record, (str, int, float, bool)) or record is None:
        return record

    if isinstance(record, Mapping):
        return {str(k): _ensure_serializable(v) for k, v in record.items()}

    if isinstance(record, (list, tuple, set)):
        return [_ensure_serializable(item) for item in record]

    # Fallback: string representation
    return str(record)

def export_to_json(records: Iterable[Mapping[str, Any]], output_path: Path) -> None:
    """
    Export a sequence of mapping-like objects to a single JSON array.
    """
    normalized: List[Any] = [_ensure_serializable(r) for r in records]
    logger.info("Writing %d records to %s", len(normalized), output_path)

    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(normalized, fh, indent=2, ensure_ascii=False)

def export_to_jsonl(records: Iterable[Mapping[str, Any]], output_path: Path) -> None:
    """
    Export a sequence of mapping-like objects to JSON Lines format.
    """
    logger.info("Writing JSONL records to %s", output_path)
    with output_path.open("w", encoding="utf-8") as fh:
        for record in records:
            line = json.dumps(_ensure_serializable(record), ensure_ascii=False)
            fh.write(line + "\n")