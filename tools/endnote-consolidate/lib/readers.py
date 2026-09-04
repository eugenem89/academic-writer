#!/usr/bin/env python3
"""
Readers that turn source libraries into canonical records.

Three input paths, in descending order of convenience:

  1. `.enl` SQLite   — EndNote X7 and later store the library as a SQLite
                       database. We open it READ-ONLY and immutable, so the
                       original file is never touched or locked.
  2. EndNote XML     — the guaranteed-lossless GUI export
                       (File > Export > Output style: EndNote Export? no —
                       File > Export, "Text file"/XML, or File > "Export" with
                       XML selected). Use this for pre-X7 libraries and as the
                       cross-check for the SQLite path.
  3. RIS             — the lossy fallback. Custom fields and some note fields
                       do not survive RIS. Only use it if nothing else exists.

Every reader stores the untouched source field dict in `_raw`.
"""

from __future__ import annotations

import html
import os
import re
import sqlite3
import xml.etree.ElementTree as ET
import zlib
from typing import Any, Iterator

from records import blank_record, coerce, set_provenance
from textnorm import normalize_doi, normalize_isbn, normalize_year, split_authors

# --------------------------------------------------------------- ref types

# EndNote's numeric reference types. Incomplete by design: unknown numbers are
# preserved verbatim as "type_<n>" rather than guessed at.
REF_TYPES = {
    0: "Generic", 2: "Artwork", 3: "Audiovisual Material",
    4: "Bill", 5: "Book Section", 6: "Book", 7: "Catalog", 8: "Case",
    9: "Computer Program", 10: "Conference Proceedings", 11: "Chart or Table",
    12: "Web Page", 13: "Classical Work", 15: "Interview",
    16: "Electronic Source", 17: "Journal Article", 18: "Legal Rule or Regulation",
    19: "Magazine Article", 20: "Map", 21: "Film or Broadcast",
    22: "Manuscript", 23: "Newspaper Article", 24: "Pamphlet", 25: "Patent",
    26: "Personal Communication", 27: "Report", 28: "Edited Book",
    29: "Equation", 30: "Figure", 31: "Statute", 32: "Thesis",
    33: "Hearing", 34: "Unpublished Work", 36: "Manuscript",
    37: "Government Document", 38: "Chart or Table", 39: "Aggregated Database",
    43: "Electronic Article", 44: "Electronic Book", 45: "Online Database",
    46: "Government Document", 47: "Conference Paper", 48: "Online Multimedia",
    49: "Dataset", 50: "Legal Rule or Regulation", 51: "Ancient Text",
    52: "Dictionary", 53: "Encyclopedia", 54: "Grant", 55: "Letter",
    56: "Blog", 57: "Serial", 58: "Standard", 59: "Database",
    63: "Press Release", 65: "Podcast",
}


def ref_type_name(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return str(value).strip()
    return REF_TYPES.get(n, f"type_{n}")


# --------------------------------------------------------------- text repair

STYLE_TAG = re.compile(r"</?style[^>]*>", re.I)
RTF_HEAD = re.compile(r"^\s*\{\\rtf", re.I)


def clean_value(value: Any) -> tuple[str, list[str]]:
    """
    Decode a raw column value into text, reporting anything suspicious so the
    verify stage can surface it rather than silently swallowing it.
    """
    flags: list[str] = []
    if value is None:
        return "", flags
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        if raw[:1] == b"\x78":                      # zlib-compressed blob
            try:
                raw = zlib.decompress(raw)
                flags.append("zlib_blob")
            except zlib.error:
                pass
        text = ""
        for enc in ("utf-8", "utf-16-le", "utf-16", "cp1252", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        if not text:
            flags.append("undecodable_blob")
            return raw.hex(), flags
        value = text.replace("\x00", "")
    s = str(value)
    if STYLE_TAG.search(s):
        s = STYLE_TAG.sub("", s)
        s = html.unescape(s)
        flags.append("style_tags_stripped")
    if RTF_HEAD.match(s):
        # Kept verbatim on purpose: silently de-RTFing 30-year-old notes is
        # exactly the kind of quiet loss this project exists to prevent.
        flags.append("rtf_payload")
    return s.strip(), flags


# --------------------------------------------------------- .enl SQLite reader

def _norm_col(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


# canonical field -> candidate column names (normalised). Order = priority.
ENL_ALIASES: dict[str, tuple[str, ...]] = {
    "title": ("title", "primarytitle"),
    "secondary_title": ("secondarytitle", "journal", "fulljournalname", "booktitle"),
    "tertiary_title": ("tertiarytitle", "seriestitle"),
    "alt_title": ("alternatetitle", "alttitle", "journalabbreviation"),
    "short_title": ("shorttitle",),
    "translated_title": ("translatedtitle",),
    "authors": ("author", "authors", "primaryauthor"),
    "secondary_authors": ("secondaryauthor", "secondaryauthors", "editor"),
    "tertiary_authors": ("tertiaryauthor", "seriesauthor", "serieseditor"),
    "subsidiary_authors": ("subsidiaryauthor", "translator", "translatedauthor"),
    "year": ("year",),
    "date": ("date", "pubdate", "publicationdate"),
    "volume": ("volume",),
    "issue": ("number", "issue"),
    "number_of_volumes": ("numberofvolumes", "numvolumes"),
    "pages": ("pages",),
    "section": ("section",),
    "edition": ("edition",),
    "publisher": ("publisher",),
    "place_published": ("placepublished", "pubplace", "placeofpublication"),
    "language": ("language",),
    "isbn": ("isbn", "isbnissn", "issn"),
    "doi": ("doi", "electronicresourcenumber", "electronicresourcenum"),
    "accession_number": ("accessionnumber", "accessionnum"),
    "call_number": ("callnumber", "callnum"),
    "label": ("label",),
    "work_type": ("typeofwork", "worktype"),
    "original_publication": ("originalpublication", "origpub"),
    "reprint_edition": ("reprintedition",),
    "remote_database": ("remotedatabasename", "nameofdatabase", "database"),
    "access_date": ("accessdate",),
    "figure": ("figure",),
    "caption": ("caption",),
    "abstract": ("abstract",),
    "notes": ("notes",),
    "research_notes": ("researchnotes",),
    "keywords": ("keywords",),
    "urls": ("url", "urls"),
    **{f"custom{i}": (f"custom{i}",) for i in range(1, 9)},
}

LIST_SPLIT = re.compile(r"[\r\n]+|(?<!\w);\s*")


def _as_list(value: str) -> list[str]:
    if not value:
        return []
    return [p.strip() for p in LIST_SPLIT.split(value) if p.strip()]


def read_enl(path: str, library: str, *, include_trash: bool = False) -> Iterator[dict[str, Any]]:
    """
    Read an EndNote X7+ `.enl` SQLite library read-only.

    Column names differ across EndNote versions, so the mapping is discovered
    at runtime from PRAGMA table_info rather than hardcoded. Any column we do
    not recognise still lands in `_raw`.
    """
    uri = f"file:{os.path.abspath(path)}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(refs)")]
        if not cols:
            raise RuntimeError(f"{path}: no `refs` table — not an X7+ .enl library")
        by_norm = {_norm_col(c): c for c in cols}
        mapping: dict[str, str] = {}
        for canon, candidates in ENL_ALIASES.items():
            for cand in candidates:
                if cand in by_norm:
                    mapping[canon] = by_norm[cand]
                    break

        id_col = by_norm.get("id") or cols[0]
        type_col = by_norm.get("referencetype") or by_norm.get("reftype")
        trash_col = by_norm.get("trashstate") or by_norm.get("trash")

        where = "" if include_trash or not trash_col else f' WHERE "{trash_col}" = 0'
        attachments = _enl_attachments(conn, by_norm)

        for row in conn.execute(f"SELECT * FROM refs{where}"):
            raw = {k: row[k] for k in row.keys()}
            rec = blank_record()
            flags: list[str] = []
            cleaned: dict[str, Any] = {}
            for key, value in raw.items():
                text, f = clean_value(value)
                cleaned[key] = text
                flags.extend(f"{key}:{x}" for x in f)
            rec["_raw"] = cleaned

            for canon, col in mapping.items():
                text = cleaned.get(col, "")
                if not text:
                    continue
                if canon in ("authors", "secondary_authors", "tertiary_authors",
                             "subsidiary_authors"):
                    rec[canon] = split_authors(text)
                elif canon in ("keywords", "urls"):
                    rec[canon] = _as_list(text)
                else:
                    rec[canon] = text

            rec["ref_type"] = ref_type_name(cleaned.get(type_col)) if type_col else ""
            rec["doi"] = normalize_doi(rec["doi"], *rec["urls"]) or rec["doi"]
            rec["isbn"] = normalize_isbn(rec["isbn"]) or rec["isbn"]
            rid = str(raw.get(id_col, ""))
            rec["file_attachments"] = attachments.get(rid, [])
            if trash_col and str(cleaned.get(trash_col, "0")) not in ("0", ""):
                flags.append("in_trash")

            set_provenance(
                rec, library=library, source_file=path, source_kind="enl",
                record_id=rid,
                extra={"flags": sorted(set(flags)), "ref_type_num": cleaned.get(type_col, "")},
            )
            yield rec
    finally:
        conn.close()


def _enl_attachments(conn: sqlite3.Connection, by_norm: dict[str, str]) -> dict[str, list[str]]:
    """
    Best-effort attachment lookup. Table naming moves between EndNote versions,
    so this discovers a table that has both a refs-id column and a path-ish
    column. Failure is non-fatal — attachments are also recoverable from the
    .Data folder, which stage 00 hashes and preserves.
    """
    out: dict[str, list[str]] = {}
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
    except sqlite3.Error:
        return out
    for table in tables:
        if "file" not in table.lower() and "attach" not in table.lower():
            continue
        try:
            cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]
        except sqlite3.Error:
            continue
        norm = {_norm_col(c): c for c in cols}
        ref_col = next((norm[k] for k in norm if k in
                        ("refsid", "recordid", "refid", "reference_id", "referenceid")), None)
        path_col = next((norm[k] for k in norm if "path" in k or "file" in k or "url" in k), None)
        if not ref_col or not path_col:
            continue
        try:
            for row in conn.execute(f'SELECT "{ref_col}", "{path_col}" FROM "{table}"'):
                rid, p = str(row[0]), clean_value(row[1])[0]
                if p:
                    out.setdefault(rid, []).append(p)
        except sqlite3.Error:
            continue
    return out


# ------------------------------------------------------------- XML reader

XML_TEXT_FIELDS = {
    "titles/title": "title",
    "titles/secondary-title": "secondary_title",
    "titles/tertiary-title": "tertiary_title",
    "titles/alt-title": "alt_title",
    "titles/short-title": "short_title",
    "titles/translated-title": "translated_title",
    "periodical/full-title": "secondary_title",
    "pages": "pages",
    "volume": "volume",
    "number": "issue",
    "num-vols": "number_of_volumes",
    "section": "section",
    "edition": "edition",
    "publisher": "publisher",
    "pub-location": "place_published",
    "language": "language",
    "isbn": "isbn",
    "accession-num": "accession_number",
    "call-num": "call_number",
    "label": "label",
    "work-type": "work_type",
    "orig-pub": "original_publication",
    "reprint-edition": "reprint_edition",
    "remote-database-name": "remote_database",
    "abstract": "abstract",
    "notes": "notes",
    "research-notes": "research_notes",
    "electronic-resource-num": "doi",
    "dates/year": "year",
    "dates/pub-dates/date": "date",
    "figure": "figure",
    "caption": "caption",
    **{f"custom{i}": f"custom{i}" for i in range(1, 9)},
}

XML_AUTHOR_FIELDS = {
    "contributors/authors/author": "authors",
    "contributors/secondary-authors/author": "secondary_authors",
    "contributors/tertiary-authors/author": "tertiary_authors",
    "contributors/subsidiary-authors/author": "subsidiary_authors",
}


def _xml_text(el: ET.Element | None) -> str:
    """EndNote wraps text in <style> elements; itertext flattens them."""
    if el is None:
        return ""
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def read_endnote_xml(path: str, library: str) -> Iterator[dict[str, Any]]:
    """Parse an EndNote XML export (`<xml><records><record>…`)."""
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        data = data.decode("utf-16").encode("utf-8")
    root = ET.fromstring(data)
    for i, record in enumerate(root.iter("record")):
        rec = blank_record()
        raw: dict[str, Any] = {}
        for child in record.iter():
            if child is record:
                continue
            text = _xml_text(child)
            if text:
                raw.setdefault(child.tag, []).append(text)
        rec["_raw"] = {k: ("\n".join(v) if len(v) > 1 else v[0]) for k, v in raw.items()}

        for xpath, canon in XML_TEXT_FIELDS.items():
            if rec.get(canon):
                continue
            value = _xml_text(record.find(xpath))
            if value:
                rec[canon] = value
        for xpath, canon in XML_AUTHOR_FIELDS.items():
            names = [_xml_text(e) for e in record.findall(xpath)]
            rec[canon] = [n for n in names if n]
        rec["keywords"] = [_xml_text(e) for e in record.findall("keywords/keyword")]
        rec["keywords"] = [k for k in rec["keywords"] if k]
        rec["urls"] = [_xml_text(e) for e in record.findall(".//urls//url") if _xml_text(e)]
        rec["file_attachments"] = [
            _xml_text(e) for e in record.findall("urls/pdf-urls/url") if _xml_text(e)
        ]
        rec["ref_type"] = (
            record.find("ref-type").get("name")
            if record.find("ref-type") is not None and record.find("ref-type").get("name")
            else ref_type_name(_xml_text(record.find("ref-type")))
        )
        rec["year"] = coerce(normalize_year(rec["year"], rec["date"]) or rec["year"])
        rec["doi"] = normalize_doi(rec["doi"], *rec["urls"]) or rec["doi"]
        rec["isbn"] = normalize_isbn(rec["isbn"]) or rec["isbn"]

        rid = _xml_text(record.find("rec-number")) or str(i)
        set_provenance(
            rec, library=library, source_file=path, source_kind="endnote-xml",
            record_id=rid,
            extra={"db": _xml_text(record.find("database"))},
        )
        yield rec


# ------------------------------------------------------------- RIS reader

RIS_MAP = {
    "TI": "title", "T1": "title", "CT": "title",
    "T2": "secondary_title", "JO": "secondary_title", "JF": "secondary_title",
    "BT": "secondary_title", "T3": "tertiary_title", "ST": "short_title",
    "VL": "volume", "IS": "issue", "SE": "section", "ET": "edition",
    "PB": "publisher", "CY": "place_published", "LA": "language",
    "SN": "isbn", "DO": "doi", "AN": "accession_number", "CN": "call_number",
    "LB": "label", "AB": "abstract", "N2": "abstract", "N1": "notes",
    "PY": "year", "Y1": "year", "DA": "date",
    **{f"C{i}": f"custom{i}" for i in range(1, 9)},
}
RIS_LIST_MAP = {
    "AU": "authors", "A1": "authors", "A2": "secondary_authors",
    "ED": "secondary_authors", "A3": "tertiary_authors",
    "A4": "subsidiary_authors", "KW": "keywords", "UR": "urls",
    "L1": "file_attachments", "L2": "file_attachments",
}
RIS_TYPES = {
    "JOUR": "Journal Article", "BOOK": "Book", "CHAP": "Book Section",
    "EDBOOK": "Edited Book", "THES": "Thesis", "CONF": "Conference Proceedings",
    "CPAPER": "Conference Paper", "RPRT": "Report", "MGZN": "Magazine Article",
    "NEWS": "Newspaper Article", "ELEC": "Web Page", "MANSCPT": "Manuscript",
    "UNPB": "Unpublished Work", "GEN": "Generic", "ANCIENT": "Ancient Text",
}
RIS_LINE = re.compile(r"^([A-Z][A-Z0-9])\s{0,2}-\s?(.*)$")


def read_ris(path: str, library: str) -> Iterator[dict[str, Any]]:
    """
    Lossy fallback reader. RIS cannot carry every EndNote custom field, so
    stage 70 flags any library ingested this way.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()

    def flush(buf: dict[str, list[str]], idx: int) -> dict[str, Any]:
        rec = blank_record()
        rec["_raw"] = {k: "\n".join(v) for k, v in buf.items()}
        for tag, values in buf.items():
            if tag in RIS_LIST_MAP:
                rec[RIS_LIST_MAP[tag]].extend(values)
            elif tag in RIS_MAP:
                canon = RIS_MAP[tag]
                joined = "\n".join(values) if canon in ("notes", "abstract") else values[0]
                if not rec[canon]:
                    rec[canon] = joined
        if "SP" in buf:
            rec["pages"] = buf["SP"][0] + (f"-{buf['EP'][0]}" if "EP" in buf else "")
        rec["ref_type"] = RIS_TYPES.get(buf.get("TY", [""])[0].strip(),
                                        buf.get("TY", [""])[0].strip())
        rec["year"] = coerce(normalize_year(rec["year"], rec["date"]) or "")
        rec["doi"] = normalize_doi(rec["doi"], *rec["urls"]) or rec["doi"]
        rec["isbn"] = normalize_isbn(rec["isbn"]) or rec["isbn"]
        set_provenance(rec, library=library, source_file=path, source_kind="ris",
                       record_id=buf.get("ID", [str(idx)])[0],
                       extra={"lossy_format": True})
        return rec

    buf: dict[str, list[str]] = {}
    idx = 0
    last_tag = ""
    for line in lines:
        m = RIS_LINE.match(line)
        if m:
            tag, value = m.group(1), m.group(2).strip()
            if tag == "ER":
                if buf:
                    yield flush(buf, idx)
                    idx += 1
                buf, last_tag = {}, ""
                continue
            buf.setdefault(tag, []).append(value)
            last_tag = tag
        elif line.strip() and last_tag:
            buf[last_tag][-1] += " " + line.strip()
    if buf:
        yield flush(buf, idx)


READERS = {"enl": read_enl, "endnote-xml": read_endnote_xml, "ris": read_ris}
