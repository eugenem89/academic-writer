#!/usr/bin/env python3
"""
Canonical record schema shared by every stage of the pipeline.

Design rule that everything else depends on: a record is *additive*. The
canonical fields are a convenience view; `_raw` always holds the untouched
field dict exactly as it came out of the source library, and `_prov` says
where it came from. No stage is ever allowed to drop `_raw` or `_prov`, so
the worst possible outcome of a bad merge is a bad *view* of data that is
still fully present in the file.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Iterator

SCHEMA_VERSION = 1

# Single-valued canonical fields.
SCALAR_FIELDS = [
    "ref_type", "title", "secondary_title", "tertiary_title", "alt_title",
    "short_title", "translated_title", "volume", "issue", "number_of_volumes",
    "pages", "section", "edition", "date", "year", "publisher",
    "place_published", "language", "isbn", "doi", "accession_number",
    "call_number", "label", "work_type", "original_publication",
    "reprint_edition", "remote_database", "access_date", "figure", "caption",
    "abstract",
]

# Multi-valued canonical fields (lists; merged by union, never by election).
LIST_FIELDS = [
    "authors", "secondary_authors", "tertiary_authors", "subsidiary_authors",
    "keywords", "urls", "file_attachments", "groups",
]

# Free-text fields that carry the researcher's own thinking. These are NEVER
# elected between duplicates -- they are concatenated with attribution. This
# is the whole point of the project.
NOTE_FIELDS = ["notes", "research_notes"] + [f"custom{i}" for i in range(1, 9)]

ALL_FIELDS = SCALAR_FIELDS + LIST_FIELDS + NOTE_FIELDS


def blank_record() -> dict[str, Any]:
    rec: dict[str, Any] = {f: "" for f in SCALAR_FIELDS}
    rec.update({f: [] for f in LIST_FIELDS})
    rec.update({f: "" for f in NOTE_FIELDS})
    rec["_prov"] = {}
    rec["_raw"] = {}
    rec["_schema"] = SCHEMA_VERSION
    return rec


def set_provenance(
    rec: dict[str, Any],
    *,
    library: str,
    source_file: str,
    source_kind: str,
    record_id: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rec["_prov"] = {
        "library": library,
        "source_file": source_file,
        "source_kind": source_kind,
        "record_id": str(record_id),
        **(extra or {}),
    }
    rec["_uid"] = f"{library}::{record_id}"
    rec["_fingerprint"] = fingerprint(rec)
    return rec


def fingerprint(rec: dict[str, Any]) -> str:
    """Content hash of the raw payload — used to spot byte-identical dupes."""
    payload = json.dumps(rec.get("_raw", {}), sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def coerce(value: Any) -> str:
    """Anything -> clean single string. Bytes and blobs are handled upstream."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "\n".join(coerce(v) for v in value if coerce(v))
    return str(value).strip()


def nonempty(rec: dict[str, Any], field: str) -> bool:
    v = rec.get(field)
    return bool(v) if not isinstance(v, str) else bool(v.strip())


# ------------------------------------------------------------------- jsonl io

def write_jsonl(path: str, rows: Iterable[dict[str, Any]]) -> int:
    n = 0
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


def read_jsonl(path: str) -> Iterator[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_jsonl(path: str) -> list[dict[str, Any]]:
    return list(read_jsonl(path))
