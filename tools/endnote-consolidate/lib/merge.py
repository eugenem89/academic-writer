#!/usr/bin/env python3
"""
Cluster -> single merged record.

Three different policies, because the three kinds of field carry three
different kinds of value:

  scalar fields  (title, publisher, volume …)  -> ELECT one, keep the rest as
                                                  variants in the ledger
  list fields    (authors, keywords, urls …)   -> UNION, order preserved
  note fields    (notes, research notes,
                  custom1-8)                   -> CONCATENATE with attribution

The note policy is the whole reason the project exists: two records for the
same book with two different marginal notes are not a duplicate to be resolved,
they are one reference with two notes. Election is never applied to them.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from records import LIST_FIELDS, NOTE_FIELDS, SCALAR_FIELDS, blank_record
from textnorm import initials, normalize_text, normalize_year, surname

# An author list is an ordered whole, not a set: unioning "Nirenberg, David"
# with "Nirenberg, D." would produce a two-author book. These fields elect the
# most complete list and keep the rest as variants; everything else unions.
AUTHOR_FIELDS = ("authors", "secondary_authors", "tertiary_authors",
                 "subsidiary_authors")

# Attribution marker. Deliberately plain ASCII (EndNote is happy with it) and
# strictly parseable, so a future script can split the notes back apart.
BLOCK_RE = re.compile(r"^--- \[from ([^\]]+)\] ---$", re.M)


def block_header(rec: dict[str, Any]) -> str:
    prov = rec.get("_prov", {})
    lib = prov.get("library", "?")
    rid = prov.get("record_id", "?")
    return f"--- [from {lib} #{rid}] ---"


def _informativeness(value: str) -> tuple[int, int, int]:
    """
    Rank candidate values for a scalar field. Longer usually means more
    complete (full journal name over abbreviation, title with subtitle over
    title without), but not at the cost of obvious junk.
    """
    v = (value or "").strip()
    has_lower = 1 if v != v.upper() else 0     # ALL-CAPS records are older/OCR-ish
    return (len(v), has_lower, -v.count("?"))


def elect_scalar(field: str, members: list[dict[str, Any]], priority: dict[str, int]
                 ) -> tuple[str, list[dict[str, Any]]]:
    """
    Pick a value and return (winner, variants). Variants list *every* distinct
    non-empty value with the records it came from — nothing is discarded.
    """
    seen: dict[str, dict[str, Any]] = {}
    for rec in members:
        value = str(rec.get(field) or "").strip()
        if not value:
            continue
        key = normalize_text(value) or value.casefold()
        entry = seen.setdefault(key, {"value": value, "from": [], "score": None})
        entry["from"].append(rec.get("_uid"))
        if _informativeness(value) > _informativeness(entry["value"]):
            entry["value"] = value

    if not seen:
        return "", []

    def rank(entry: dict[str, Any]) -> tuple:
        best_priority = max(
            (priority.get(uid.split("::", 1)[0], 0) for uid in entry["from"]), default=0)
        return (_informativeness(entry["value"]), len(entry["from"]), best_priority)

    ordered = sorted(seen.values(), key=rank, reverse=True)
    winner = ordered[0]["value"]
    variants = [{"value": e["value"], "from": e["from"]} for e in ordered]
    return winner, variants


def name_key(name: str) -> str:
    """Surname plus first given initial — the identity of a person across
    cataloguing styles, without collapsing J. Cohen into M. Cohen."""
    ini = initials(name)
    return f"{surname(name)}|{ini[:1]}" if ini else surname(name)


def _list_rank(names: list[str]) -> tuple[int, int]:
    """More names wins; then fuller names (David beats D.)."""
    return (len(names), sum(len(str(n)) for n in names))


def elect_list(field: str, members: list[dict[str, Any]], priority: dict[str, int]
               ) -> tuple[list[str], list[dict[str, Any]]]:
    """
    Elect one author list. Lists naming the same people in the same order are
    treated as one candidate (the fullest spelling wins); a list naming
    genuinely different or additional people is a separate variant and is kept.
    """
    seen: dict[str, dict[str, Any]] = {}
    for rec in members:
        names = [str(n).strip() for n in (rec.get(field) or []) if str(n).strip()]
        if not names:
            continue
        key = "||".join(name_key(n) for n in names)
        entry = seen.setdefault(key, {"value": names, "from": []})
        entry["from"].append(rec.get("_uid"))
        if _list_rank(names) > _list_rank(entry["value"]):
            entry["value"] = names

    if not seen:
        return [], []

    def rank(entry: dict[str, Any]) -> tuple:
        best_priority = max(
            (priority.get(str(uid).split("::", 1)[0], 0) for uid in entry["from"]), default=0)
        return (_list_rank(entry["value"]), len(entry["from"]), best_priority)

    ordered = sorted(seen.values(), key=rank, reverse=True)
    variants = [{"value": e["value"], "from": e["from"]} for e in ordered]
    return ordered[0]["value"], variants


def union_list(field: str, members: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for rec in members:
        for value in rec.get(field) or []:
            value = str(value).strip()
            if not value:
                continue
            key = normalize_text(value) or value.casefold()
            if key not in seen:
                seen.add(key)
                out.append(value)
    return out


def concat_notes(field: str, members: list[dict[str, Any]]) -> tuple[str, int]:
    """
    Concatenate distinct note texts with attribution. Identical text repeated
    across libraries is emitted once (with every source listed), so the merged
    note stays readable instead of triplicating boilerplate.
    """
    groups: list[dict[str, Any]] = []
    index: dict[str, dict[str, Any]] = {}
    for rec in members:
        text = str(rec.get(field) or "").strip()
        if not text:
            continue
        key = re.sub(r"\s+", " ", normalize_text(text, drop_articles=False))
        if key in index:
            index[key]["sources"].append(rec)
            continue
        entry = {"text": text, "sources": [rec]}
        index[key] = entry
        groups.append(entry)

    if not groups:
        return "", 0
    if len(groups) == 1 and len(groups[0]["sources"]) == len(members):
        return groups[0]["text"], 1  # everyone agreed; no need to shout about it

    chunks = []
    for entry in groups:
        heads = ", ".join(
            f"{r['_prov'].get('library', '?')} #{r['_prov'].get('record_id', '?')}"
            for r in entry["sources"])
        chunks.append(f"--- [from {heads}] ---\n{entry['text']}")
    return "\n\n".join(chunks), len(groups)


def merge_cluster(members: list[dict[str, Any]], merge_id: str, *,
                  priority: dict[str, int] | None = None,
                  notes_limit: int = 0) -> tuple[dict[str, Any], dict[str, str]]:
    """
    Returns (merged_record, overflow) where overflow maps field -> full text
    that was too long for an EndNote field and must be written to a sidecar.
    """
    priority = priority or {}
    merged = blank_record()
    variants: dict[str, list[dict[str, Any]]] = {}
    overflow: dict[str, str] = {}

    for field in SCALAR_FIELDS:
        winner, vs = elect_scalar(field, members, priority)
        merged[field] = winner
        if len(vs) > 1:
            variants[field] = vs

    for field in LIST_FIELDS:
        if field in AUTHOR_FIELDS:
            elected, vs = elect_list(field, members, priority)
            merged[field] = elected
            if len(vs) > 1:
                variants[field] = vs
        else:
            merged[field] = union_list(field, members)

    note_block_counts: dict[str, int] = {}
    for field in NOTE_FIELDS:
        text, blocks = concat_notes(field, members)
        note_block_counts[field] = blocks
        if notes_limit and len(text) > notes_limit:
            overflow[field] = text
            keep = text[: max(0, notes_limit - 200)]
            merged[field] = (
                keep.rstrip()
                + f"\n\n--- [TRUNCATED: full text in overflow/{merge_id}.{field}.txt] ---"
            )
        else:
            merged[field] = text

    # ref_type: majority vote, most specific wins ties.
    types = Counter(r.get("ref_type") for r in members if r.get("ref_type"))
    if types:
        top = max(types.values())
        merged["ref_type"] = sorted(
            [t for t, c in types.items() if c == top], key=lambda t: (-len(t), t))[0]

    years = [normalize_year(r.get("year"), r.get("date")) for r in members]
    years = [y for y in years if y]
    if years:
        merged["year"] = str(min(years))  # earliest = original publication

    merged["_merge_id"] = merge_id
    merged["_members"] = [r.get("_uid") for r in members]
    merged["_member_count"] = len(members)
    merged["_libraries"] = sorted({r.get("_prov", {}).get("library", "?") for r in members})
    merged["_variants"] = variants
    merged["_note_blocks"] = {k: v for k, v in note_block_counts.items() if v}
    merged["_prov"] = {"kind": "merged", "from": merged["_members"]}
    # Every source record's untouched payload rides along. This is the
    # guarantee: even a wrong merge loses nothing that cannot be recovered.
    merged["_raw"] = {r.get("_uid"): r.get("_raw", {}) for r in members}
    merged["_source_records"] = [
        {"uid": r.get("_uid"), "prov": r.get("_prov", {}),
         "fingerprint": r.get("_fingerprint")} for r in members
    ]
    return merged, overflow
