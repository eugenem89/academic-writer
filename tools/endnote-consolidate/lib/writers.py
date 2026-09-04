#!/usr/bin/env python3
"""
Output writers: EndNote XML (re-import), CSV (eyeballing), and the
academic-writer `sources.json` registry (bridge into this plugin's citation
auditor).
"""

from __future__ import annotations

import csv
import json
import re
import xml.etree.ElementTree as ET
from typing import Any, Iterable

from readers import REF_TYPES
from textnorm import normalize_year

# EndNote's canonical export ids for the types a humanities library actually
# uses. Several names appear against more than one internal id, so these are
# pinned explicitly rather than reverse-derived.
PREFERRED_NUM = {
    "Journal Article": 17, "Book": 6, "Book Section": 5, "Edited Book": 28,
    "Thesis": 32, "Manuscript": 36, "Ancient Text": 51, "Web Page": 12,
    "Report": 27, "Conference Paper": 47, "Conference Proceedings": 10,
    "Newspaper Article": 23, "Magazine Article": 19, "Electronic Article": 43,
    "Electronic Book": 44, "Unpublished Work": 34, "Letter": 55,
    "Personal Communication": 26, "Dictionary": 52, "Encyclopedia": 53,
    "Government Document": 46, "Map": 20, "Pamphlet": 24, "Generic": 13,
}

NAME_TO_NUM: dict[str, int] = {}
for _num, _name in sorted(REF_TYPES.items()):
    NAME_TO_NUM.setdefault(_name, _num)
NAME_TO_NUM.update(PREFERRED_NUM)

XML_SCALARS = [
    ("pages", "pages"), ("volume", "volume"), ("issue", "number"),
    ("number_of_volumes", "num-vols"), ("section", "section"),
    ("edition", "edition"), ("publisher", "publisher"),
    ("place_published", "pub-location"), ("language", "language"),
    ("isbn", "isbn"), ("accession_number", "accession-num"),
    ("call_number", "call-num"), ("label", "label"),
    ("work_type", "work-type"), ("original_publication", "orig-pub"),
    ("reprint_edition", "reprint-edition"),
    ("remote_database", "remote-database-name"),
    ("abstract", "abstract"), ("notes", "notes"),
    ("research_notes", "research-notes"), ("doi", "electronic-resource-num"),
    ("figure", "figure"), ("caption", "caption"),
] + [(f"custom{i}", f"custom{i}") for i in range(1, 9)]

XML_TITLES = [("title", "title"), ("secondary_title", "secondary-title"),
              ("tertiary_title", "tertiary-title"), ("alt_title", "alt-title"),
              ("short_title", "short-title"),
              ("translated_title", "translated-title")]

XML_CONTRIBUTORS = [("authors", "authors"), ("secondary_authors", "secondary-authors"),
                    ("tertiary_authors", "tertiary-authors"),
                    ("subsidiary_authors", "subsidiary-authors")]

# XML 1.0 forbids most control characters outright; strip them rather than
# emitting a file EndNote will refuse to open.
CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _sub(parent: ET.Element, tag: str, text: str | None) -> ET.Element | None:
    text = (text or "").strip()
    if not text:
        return None
    el = ET.SubElement(parent, tag)
    el.text = CTRL.sub("", text)
    return el


def record_to_xml(rec: dict[str, Any], rec_number: int) -> ET.Element:
    record = ET.Element("record")
    _sub(record, "rec-number", str(rec_number))

    type_name = rec.get("ref_type") or "Journal Article"
    num = NAME_TO_NUM.get(type_name)
    if num is None:
        m = re.match(r"type_(\d+)$", str(type_name))
        num = int(m.group(1)) if m else 17
        type_name = str(type_name)
    rt = ET.SubElement(record, "ref-type")
    rt.set("name", type_name)
    rt.text = str(num)

    contributors = ET.Element("contributors")
    for field, tag in XML_CONTRIBUTORS:
        names = [n for n in (rec.get(field) or []) if str(n).strip()]
        if names:
            group = ET.SubElement(contributors, tag)
            for name in names:
                _sub(group, "author", str(name))
    if len(contributors):
        record.append(contributors)

    titles = ET.Element("titles")
    for field, tag in XML_TITLES:
        _sub(titles, tag, rec.get(field))
    if len(titles):
        record.append(titles)

    year = rec.get("year") or ""
    date = rec.get("date") or ""
    if year or date:
        dates = ET.SubElement(record, "dates")
        _sub(dates, "year", str(year))
        if date:
            pub = ET.SubElement(dates, "pub-dates")
            _sub(pub, "date", str(date))

    for field, tag in XML_SCALARS:
        _sub(record, tag, rec.get(field))

    keywords = [k for k in (rec.get("keywords") or []) if str(k).strip()]
    if keywords:
        kws = ET.SubElement(record, "keywords")
        for kw in keywords:
            _sub(kws, "keyword", str(kw))

    urls = [u for u in (rec.get("urls") or []) if str(u).strip()]
    pdfs = [u for u in (rec.get("file_attachments") or []) if str(u).strip()]
    if urls or pdfs:
        urls_el = ET.SubElement(record, "urls")
        if urls:
            related = ET.SubElement(urls_el, "related-urls")
            for u in urls:
                _sub(related, "url", str(u))
        if pdfs:
            pdf_el = ET.SubElement(urls_el, "pdf-urls")
            for u in pdfs:
                _sub(pdf_el, "url", str(u))
    return record


def write_endnote_xml(path: str, records: Iterable[dict[str, Any]]) -> int:
    root = ET.Element("xml")
    container = ET.SubElement(root, "records")
    n = 0
    for i, rec in enumerate(records, start=1):
        container.append(record_to_xml(rec, i))
        n += 1
    ET.indent(root, space="  ")
    tree = ET.ElementTree(root)
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return n


# ------------------------------------------------------------------- csv/json

CSV_COLUMNS = ["_merge_id", "_member_count", "_libraries", "ref_type", "authors",
               "year", "title", "secondary_title", "publisher", "volume",
               "issue", "pages", "doi", "isbn", "keywords", "notes",
               "research_notes", "_variant_fields", "_members"]


def write_csv(path: str, records: Iterable[dict[str, Any]],
              columns: list[str] | None = None) -> int:
    columns = columns or CSV_COLUMNS
    n = 0
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(columns)
        for rec in records:
            row = []
            for col in columns:
                if col == "_variant_fields":
                    row.append("; ".join(sorted(rec.get("_variants", {}))))
                    continue
                value = rec.get(col, "")
                if isinstance(value, list):
                    value = "; ".join(str(v) for v in value)
                elif isinstance(value, dict):
                    value = json.dumps(value, ensure_ascii=False)
                row.append(value)
            writer.writerow(row)
            n += 1
    return n


ARTICLE_TYPES = {"Journal Article", "Electronic Article", "Magazine Article",
                 "Newspaper Article"}


def to_sources_json(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Emit the shape `.academic-helper/sources.json` expects, so the consolidated
    library can feed the auditor's Check D metadata verification directly.

    `extractionConfidence` is genuinely computed, not stamped: a field is
    "high" only when every merged source record agreed on it. Where the
    libraries disagreed, the auditor gets "low" and tags the citation
    [NEEDS REVIEW] rather than trusting a coin-flip election.
    """
    out = []
    for rec in records:
        variants = rec.get("_variants", {})
        is_article = (rec.get("ref_type") or "") in ARTICLE_TYPES

        def confidence(field: str) -> str:
            if not str(rec.get(field) or "").strip():
                return "none"
            return "low" if len(variants.get(field, [])) > 1 else "high"

        authors = rec.get("authors") or rec.get("secondary_authors") or []
        out.append({
            "sourceId": rec.get("_merge_id"),
            "workTitle": rec.get("title", ""),
            "author": "; ".join(str(a) for a in authors),
            "year": normalize_year(rec.get("year"), rec.get("date")),
            "journal": rec.get("secondary_title", "") if is_article else "",
            "publisher": rec.get("publisher", "") if not is_article else "",
            "volume": rec.get("volume", ""),
            "issue": rec.get("issue", ""),
            "pages": rec.get("pages", ""),
            "doi": rec.get("doi", ""),
            "isbn": rec.get("isbn", ""),
            "refType": rec.get("ref_type", ""),
            "extractionConfidence": {
                f: confidence(f) for f in
                ("title", "year", "publisher", "secondary_title", "volume", "issue", "pages")
            },
            "provenance": {
                "mergedFrom": rec.get("_members", []),
                "libraries": rec.get("_libraries", []),
            },
        })
    return out


def write_json(path: str, payload: Any) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
