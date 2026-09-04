#!/usr/bin/env python3
"""
Text normalisation for multilingual bibliographic matching.

Nirenberg-shaped corpora are Latin (English/Spanish/Catalan/French/German/
Italian/Portuguese), Hebrew, and Arabic. The rules below are deliberately
script-aware: stripping "diacritics" is correct for Latin (Muñoz -> Munoz)
and *wrong* for Hebrew/Arabic in different ways (Hebrew niqqud and Arabic
harakat are optional pointing that should be dropped; the letters must not be).

Stdlib only. No third-party dependency is required anywhere in this pipeline.
"""

from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------- script ids

HEBREW = re.compile(r"[֐-׿יִ-ﭏ]")
ARABIC = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
CYRILLIC = re.compile(r"[Ѐ-ӿ]")
GREEK = re.compile(r"[Ͱ-Ͽἀ-῿]")

# Hebrew niqqud + cantillation, Arabic harakat + tatweel: pointing, not letters.
HEB_POINTS = re.compile(r"[֑-ֽֿׁ-ׇ]")
ARA_POINTS = re.compile(r"[ً-ٰٟۖ-ۭـ]")

# Leading articles worth ignoring when comparing titles, by script.
LATIN_ARTICLES = (
    "the", "a", "an",
    "el", "la", "los", "las", "lo", "un", "una", "unos", "unas",
    "le", "les", "l", "un", "une", "des", "du", "de", "der", "die", "das",
    "den", "dem", "ein", "eine", "einer", "eines", "il", "lo", "gli", "i",
    "o", "os", "as", "um", "uma", "het", "een",
)
HEB_ARTICLE = re.compile(r"^ה(?=\w)")
ARA_ARTICLE = re.compile(r"^ال(?=\w)")

# Punctuation / structural noise that never carries matching signal.
PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
WS = re.compile(r"\s+")

# Subtitle separators: EndNote records disagree constantly about whether the
# subtitle made it into the Title field, so we keep a main-title-only key too.
SUBTITLE_SPLIT = re.compile(r"\s*[:;]\s+|\s+[-–—]\s+")


def dominant_script(s: str) -> str:
    """Cheap script detector used to pick the right normalisation branch."""
    if not s:
        return "latin"
    counts = {
        "hebrew": len(HEBREW.findall(s)),
        "arabic": len(ARABIC.findall(s)),
        "cyrillic": len(CYRILLIC.findall(s)),
        "greek": len(GREEK.findall(s)),
    }
    best = max(counts, key=lambda k: counts[k])
    return best if counts[best] >= 2 else "latin"


def strip_latin_diacritics(s: str) -> str:
    """Munoz == Muñoz, Gorres == Görres. Latin only."""
    decomposed = unicodedata.normalize("NFD", s)
    out = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return unicodedata.normalize("NFC", out)


def normalize_text(s: str | None, *, drop_articles: bool = True) -> str:
    """
    Canonical comparison form. Script-aware: Latin loses diacritics, Hebrew
    loses niqqud, Arabic loses harakat/tatweel, everything loses case,
    punctuation, and leading articles.
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    s = s.replace("‏", "").replace("‎", "")  # bidi marks
    script = dominant_script(s)
    if script == "hebrew":
        s = HEB_POINTS.sub("", s)
    elif script == "arabic":
        s = ARA_POINTS.sub("", s)
    else:
        s = strip_latin_diacritics(s)
    s = s.casefold()
    s = PUNCT.sub(" ", s)
    s = WS.sub(" ", s).strip()
    if drop_articles and s:
        if script == "hebrew":
            s = HEB_ARTICLE.sub("", s)
        elif script == "arabic":
            s = ARA_ARTICLE.sub("", s)
        else:
            head, _, rest = s.partition(" ")
            if rest and head in LATIN_ARTICLES:
                s = rest
    return s.strip()


def tokens(s: str | None) -> list[str]:
    n = normalize_text(s)
    return n.split() if n else []


def title_key(s: str | None) -> str:
    """Full normalised title — the primary blocking/comparison key."""
    return normalize_text(s)


def main_title_key(s: str | None) -> str:
    """
    Title with the subtitle amputated. Catches the very common pair
    'Communities of Violence' / 'Communities of Violence: Persecution of
    Minorities in the Middle Ages' recorded across two libraries.
    """
    if not s:
        return ""
    head = SUBTITLE_SPLIT.split(str(s), maxsplit=1)[0]
    return normalize_text(head)


def sorted_token_key(s: str | None, limit: int = 8) -> str:
    """Order-insensitive title key; survives transposed/reordered titles."""
    t = sorted(set(tokens(s)))
    return " ".join(t[:limit])


# ---------------------------------------------------------------- identifiers

DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:a-z0-9<>\[\]]+", re.I)


def normalize_doi(*values: str | None) -> str:
    """Pull a bare DOI out of anything (URL, 'doi:', ERN field, free text)."""
    for v in values:
        if not v:
            continue
        m = DOI_RE.search(str(v))
        if m:
            return m.group(0).rstrip(".,;)]>").casefold()
    return ""


def _isbn10_to_13(core: str) -> str:
    body = "978" + core[:9]
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(body))
    return body + str((10 - total % 10) % 10)


def normalize_isbn(*values: str | None) -> str:
    """Return a single ISBN-13 (first parseable one). ISBN-10 is upconverted."""
    for v in values:
        if not v:
            continue
        for raw in re.split(r"[\s,;/|]+", str(v)):
            core = re.sub(r"[^0-9Xx]", "", raw)
            if len(core) == 13 and core.isdigit():
                return core
            if len(core) == 10:
                try:
                    return _isbn10_to_13(core.upper())
                except ValueError:
                    continue
    return ""


YEAR_RE = re.compile(r"(?<![0-9])(1[0-9]{3}|20[0-9]{2})(?![0-9])")


def normalize_year(*values: str | None) -> int | None:
    """
    Year out of EndNote's zoo of date strings: '1996', 'c1996', '1996-1997',
    'Spring 1996', '[1996]', 'n.d.'. Returns the earliest plausible year.
    """
    for v in values:
        if v is None:
            continue
        found = YEAR_RE.findall(str(v))
        if found:
            return min(int(y) for y in found)
    return None


def normalize_pages(value: str | None) -> str:
    if not value:
        return ""
    return WS.sub("", str(value)).replace("--", "-").replace("–", "-")


# ---------------------------------------------------------------- author names

NAME_NOISE = re.compile(
    r"\b(jr|sr|ii|iii|iv|ed|eds|editor|editors|trans|translator|comp|"
    r"et al|and others)\b\.?", re.I
)


def split_authors(value) -> list[str]:
    """
    EndNote stores authors newline-separated in .enl and as repeated <author>
    elements in XML. RIS repeats AU tags. Accept any of those shapes.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        parts: list[str] = []
        for v in value:
            parts.extend(split_authors(v))
        return parts
    s = str(value).strip()
    if not s:
        return []
    if "\n" in s or "\r" in s:
        parts = re.split(r"[\r\n]+", s)
    elif ";" in s:
        parts = s.split(";")
    else:
        parts = [s]
    return [p.strip().strip(",") for p in parts if p.strip().strip(",")]


def surname(name: str) -> str:
    """
    Best-effort surname. Handles 'Nirenberg, David', 'David Nirenberg',
    'Ibn Verga, Solomon', and Hebrew 'ניתן, שם'. Particles are kept
    ('van der Berg' -> 'van der berg') because dropping them merges families.
    """
    if not name:
        return ""
    n = NAME_NOISE.sub("", str(name)).strip().strip(",")
    if "," in n:
        head = n.split(",", 1)[0]
    else:
        parts = n.split()
        head = parts[-1] if parts else n
    return normalize_text(head, drop_articles=False)


def initials(name: str) -> str:
    """Given-name initials, for distinguishing J. Cohen from M. Cohen."""
    if not name or "," not in name:
        parts = [p for p in str(name).split() if p]
        given = parts[:-1]
    else:
        given = str(name).split(",", 1)[1].split()
    out = ""
    for g in given:
        g = normalize_text(g, drop_articles=False)
        if g:
            out += g[0]
    return out


def author_keys(value) -> list[str]:
    return [s for s in (surname(a) for a in split_authors(value)) if s]


def first_author_key(value) -> str:
    keys = author_keys(value)
    return keys[0] if keys else ""
