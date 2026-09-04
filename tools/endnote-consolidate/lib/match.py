#!/usr/bin/env python3
"""
Blocking, pairwise scoring, and clustering.

The scoring here is deliberately conservative and *asymmetric in its errors*:
a missed duplicate costs one extra row in the final library; a wrong merge
costs a lost distinction between (say) the 1996 and 2015 editions of a book,
or between a chapter and the volume it sits in. So anything that smells like
a real bibliographic distinction is routed to review rather than auto-merged,
even when the strings match almost perfectly.

Stdlib only; `rapidfuzz` is used automatically if installed, purely for speed.
"""

from __future__ import annotations

import difflib
import re
from collections import defaultdict
from typing import Any, Iterable

from textnorm import (author_keys, first_author_key, main_title_key,
                      normalize_pages, normalize_year, sorted_token_key,
                      title_key, tokens)

try:  # optional accelerator, never required
    from rapidfuzz.distance import JaroWinkler as _JW  # type: ignore

    def _ratio(a: str, b: str) -> float:
        return _JW.normalized_similarity(a, b)
except Exception:  # pragma: no cover - exercised only when rapidfuzz absent
    def _ratio(a: str, b: str) -> float:
        return difflib.SequenceMatcher(None, a, b).ratio()


# ------------------------------------------------------------------ defaults

DEFAULT_WEIGHTS = {
    "title": 0.50,
    "authors": 0.25,
    "year": 0.10,
    "container": 0.10,
    "detail": 0.05,
}
DEFAULT_THRESHOLDS = {
    "auto_merge": 0.92,     # >= this and unblocked -> merged without a human
    "review_low": 0.72,     # >= this and < auto_merge -> review queue
    "max_block": 400,       # blocks larger than this are skipped (and reported)
    "year_slack": 1,        # years within this are treated as the same year
}

# Reference types that must never be auto-merged across the divide. A chapter
# and the book that contains it share title-ish and author-ish strings all the
# time, and collapsing them destroys the citation.
TYPE_FAMILIES = {
    "Book": "book", "Edited Book": "book", "Electronic Book": "book",
    "Book Section": "chapter",
    "Journal Article": "article", "Electronic Article": "article",
    "Magazine Article": "article", "Newspaper Article": "article",
    "Thesis": "thesis",
    "Manuscript": "manuscript", "Ancient Text": "manuscript",
    "Conference Paper": "conference", "Conference Proceedings": "conference",
}

EDITION_RE = re.compile(r"(\d+)\s*(?:st|nd|rd|th|e|ª|º)?\b|\b(first|second|third|fourth|fifth"
                        r"|sixth|seventh|eighth|ninth|tenth)\b", re.I)
EDITION_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
                 "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10}


def edition_number(value: str | None) -> int | None:
    if not value:
        return None
    m = EDITION_RE.search(str(value))
    if not m:
        return None
    if m.group(1):
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return EDITION_WORDS.get((m.group(2) or "").lower())


# ------------------------------------------------------- precomputed keys

# Normalising a title costs a Unicode decomposition and several regex passes.
# Doing that inside the pair loop dominated the runtime, so every record's keys
# are computed exactly once and cached on the record under `_k`.
MAX_RATIO_LEN = 160  # difflib is quadratic; titles this long are already decided


def keys_for(rec: dict[str, Any]) -> dict[str, Any]:
    cached = rec.get("_k")
    if cached is not None:
        return cached
    tk = title_key(rec.get("title"))
    mt = main_title_key(rec.get("title"))
    authors = author_keys(rec.get("authors")) or author_keys(rec.get("secondary_authors"))
    container = title_key(rec.get("secondary_title")) or title_key(rec.get("publisher"))
    cached = {
        "title": tk[:MAX_RATIO_LEN],
        "title_tokens": frozenset(tk.split()),
        "main_title": mt[:MAX_RATIO_LEN],
        "sorted_title": sorted_token_key(rec.get("title"))[:MAX_RATIO_LEN],
        "authors": authors,
        "author_set": frozenset(authors),
        "year": normalize_year(rec.get("year"), rec.get("date")),
        "container": container[:MAX_RATIO_LEN],
        "family": TYPE_FAMILIES.get((rec.get("ref_type") or "").strip(), ""),
        "pages": normalize_pages(rec.get("pages")),
        "edition": edition_number(rec.get("edition")),
        "has_edition": bool(str(rec.get("edition") or "").strip()),
        "volume": str(rec.get("volume") or "").strip(),
        "issue": str(rec.get("issue") or "").strip(),
        "translators": frozenset(author_keys(rec.get("subsidiary_authors"))),
        "language": title_key(rec.get("language")),
    }
    rec["_k"] = cached
    return cached


def prepare(records: list[dict[str, Any]]) -> None:
    for rec in records:
        keys_for(rec)


# ------------------------------------------------------------------ blocking

def block_keys(rec: dict[str, Any], cfg: dict[str, Any]) -> list[str]:
    """
    Cheap keys that put plausible duplicates in the same bucket. A pair is only
    ever scored if it shares at least one key, which is what keeps this
    tractable on a hundred thousand records.
    """
    keys: list[str] = []
    if rec.get("doi"):
        keys.append(f"doi:{rec['doi']}")
    if rec.get("isbn"):
        keys.append(f"isbn:{rec['isbn']}")

    k = keys_for(rec)
    tk, mt = k["title"], k["main_title"]
    toks = tk.split()
    if toks:
        keys.append("t4:" + " ".join(toks[:4]))
        keys.append("tl:" + " ".join(toks[-3:]))
    if mt and mt != tk:
        keys.append("mt:" + mt)
    if k["sorted_title"]:
        keys.append("st:" + k["sorted_title"])

    fa = k["authors"][0] if k["authors"] else ""
    year = k["year"]
    if fa:
        if year:
            slack = int(cfg.get("year_slack", 1))
            for delta in range(-slack, slack + 1):
                keys.append(f"ay:{fa}:{year + delta}")
        keys.append(f"a:{fa}:" + " ".join(toks[:2]))
    return [k for k in keys if k.strip(": ")]


def build_blocks(records: list[dict[str, Any]], cfg: dict[str, Any]
                 ) -> tuple[dict[str, list[int]], list[str]]:
    blocks: dict[str, list[int]] = defaultdict(list)
    for i, rec in enumerate(records):
        for key in block_keys(rec, cfg):
            blocks[key].append(i)
    oversized = []
    max_block = int(cfg.get("max_block", 400))
    for key in list(blocks):
        if len(blocks[key]) < 2:
            del blocks[key]
        elif len(blocks[key]) > max_block:
            oversized.append(f"{key} ({len(blocks[key])} records)")
            del blocks[key]
    return blocks, oversized


def candidate_pairs(records: list[dict[str, Any]], cfg: dict[str, Any]
                    ) -> tuple[set[tuple[int, int]], list[str]]:
    blocks, oversized = build_blocks(records, cfg)
    pairs: set[tuple[int, int]] = set()
    for members in blocks.values():
        members = sorted(members)
        for a_idx in range(len(members)):
            for b_idx in range(a_idx + 1, len(members)):
                pairs.add((members[a_idx], members[b_idx]))
    return pairs, oversized


# ------------------------------------------------------------------- scoring

def _jaccard_sets(sa: frozenset, sb: frozenset) -> float:
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    return _jaccard_sets(frozenset(a), frozenset(b))


# Below this token overlap two titles cannot reach any useful score, so the
# expensive character-level comparisons are skipped entirely.
JACCARD_GATE = 0.15


def title_similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    ka, kb = keys_for(a), keys_for(b)
    ta, tb = ka["title"], kb["title"]
    if not ta or not tb:
        return 0.0
    jac = _jaccard_sets(ka["title_tokens"], kb["title_tokens"])
    if jac < JACCARD_GATE and ta[:12] != tb[:12]:
        return jac
    scores = [_ratio(ta, tb), jac]
    ma, mb = ka["main_title"], kb["main_title"]
    if ma and mb and min(ma.count(" "), mb.count(" ")) >= 1:
        # One library kept the subtitle, the other didn't.
        scores.append(_ratio(ma, mb) * 0.97)
    scores.append(_ratio(ka["sorted_title"], kb["sorted_title"]) * 0.95)
    return max(scores)


def author_similarity(a: dict[str, Any], b: dict[str, Any]) -> float | None:
    """None means "no evidence" — the caller redistributes the weight."""
    ka = keys_for(a)["authors"]
    kb = keys_for(b)["authors"]
    if not ka or not kb:
        return None
    score = _jaccard_sets(keys_for(a)["author_set"], keys_for(b)["author_set"])
    if ka[0] == kb[0]:
        score = max(score, 0.75)
    elif _ratio(ka[0], kb[0]) > 0.9:
        score = max(score, 0.65)
    return score


def year_similarity(a: dict[str, Any], b: dict[str, Any], slack: int
                    ) -> tuple[float | None, int | None]:
    ya, yb = keys_for(a)["year"], keys_for(b)["year"]
    if ya is None or yb is None:
        return None, None
    delta = abs(ya - yb)
    if delta <= slack:
        return 1.0, delta
    if delta <= 3:
        return 0.5, delta
    return 0.0, delta


def container_similarity(a: dict[str, Any], b: dict[str, Any]) -> float | None:
    ca, cb = keys_for(a)["container"], keys_for(b)["container"]
    if not ca or not cb:
        return None
    return _ratio(ca, cb)


def detail_similarity(a: dict[str, Any], b: dict[str, Any]) -> float | None:
    ka, kb = keys_for(a), keys_for(b)
    hits, total = 0.0, 0.0
    for field in ("volume", "issue", "pages"):
        va, vb = ka[field], kb[field]
        if va and vb:
            total += 1
            hits += 1.0 if va == vb else 0.0
    return hits / total if total else None


def family(rec: dict[str, Any]) -> str:
    return keys_for(rec)["family"]


def blockers(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    """
    Real bibliographic distinctions. Any hit here means the pair goes to a
    human (or to stage 40) no matter how well the strings match.
    """
    out: list[str] = []
    ka, kb = keys_for(a), keys_for(b)

    fa, fb = ka["family"], kb["family"]
    if fa and fb and fa != fb:
        out.append(f"type_family:{fa}!={fb}")

    ea, eb = ka["edition"], kb["edition"]
    if ea and eb and ea != eb:
        out.append(f"edition:{ea}!={eb}")
    elif ka["has_edition"] != kb["has_edition"]:
        out.append("edition:one_side_only")

    va, vb = ka["volume"], kb["volume"]
    if va and vb and va != vb:
        out.append(f"volume:{va}!={vb}")

    ta, tb = ka["translators"], kb["translators"]
    if ta and tb and not (ta & tb):
        out.append("translator:disjoint")

    la, lb = ka["language"], kb["language"]
    if la and lb and la != lb:
        out.append(f"language:{la}!={lb}")

    ya, yb = ka["year"], kb["year"]
    if ya and yb and abs(ya - yb) > 3 and (fa in ("book", "chapter") or fb in ("book", "chapter")):
        out.append(f"year_gap:{abs(ya - yb)}")  # reprint / new edition, probably

    pa, pb = ka["pages"], kb["pages"]
    if pa and pb and pa != pb and fa == "article" and fb == "article":
        # Same journal issue, different page ranges = two different articles.
        if container_similarity(a, b) > 0.9 and not _pages_overlap(pa, pb):
            out.append(f"pages:{pa}!={pb}")
    return out


def _pages_overlap(pa: str, pb: str) -> bool:
    def span(p: str) -> tuple[int, int] | None:
        nums = [int(n) for n in re.findall(r"\d+", p)]
        if not nums:
            return None
        return min(nums), max(nums)
    sa, sb = span(pa), span(pb)
    if not sa or not sb:
        return True
    return sa[0] <= sb[1] and sb[0] <= sa[1]


def score_pair(a: dict[str, Any], b: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    weights = {**DEFAULT_WEIGHTS, **cfg.get("weights", {})}
    slack = int(cfg.get("year_slack", 1))

    reasons: list[str] = []
    hard = 0.0
    if a.get("doi") and a["doi"] == b.get("doi"):
        hard, _ = 1.0, reasons.append("same_doi")
    elif a.get("isbn") and a["isbn"] == b.get("isbn"):
        hard, _ = 0.97, reasons.append("same_isbn")

    t = title_similarity(a, b)
    au = author_similarity(a, b)
    y, y_delta = year_similarity(a, b, slack)
    c = container_similarity(a, b)
    d = detail_similarity(a, b)

    # Components with no evidence on either side (a book has no volume/issue,
    # an old record has no year) are dropped and their weight is redistributed
    # across the components that *do* have evidence. Otherwise sparse records —
    # which is most of a 30-year-old library — could never clear threshold.
    present = {"title": t, "authors": au, "year": y, "container": c, "detail": d}
    present = {k: v for k, v in present.items() if v is not None}
    total_weight = sum(weights[k] for k in present) or 1.0
    weighted = sum(weights[k] * v for k, v in present.items()) / total_weight
    if len(present) <= 1:
        # Title alone is not enough to merge anything.
        weighted *= 0.8
        reasons.append("thin_evidence")

    score = max(hard, weighted)
    if hard and t < 0.55:
        # Identifier says same, strings say otherwise: a real conflict worth
        # a human glance rather than a silent merge.
        reasons.append("identifier_title_conflict")
        score = min(score, 0.9)

    blocked = blockers(a, b)
    return {
        "score": round(score, 4),
        "components": {k: round(v, 4) for k, v in present.items()},
        "year_delta": y_delta,
        "reasons": reasons,
        "blockers": blocked,
    }


# ---------------------------------------------------------------- clustering

class UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)

    def groups(self) -> dict[int, list[int]]:
        out: dict[int, list[int]] = defaultdict(list)
        for i in range(len(self.parent)):
            out[self.find(i)].append(i)
        return out


def cluster(n: int, merge_pairs: Iterable[tuple[int, int]]) -> list[list[int]]:
    uf = UnionFind(n)
    for a, b in merge_pairs:
        uf.union(a, b)
    return sorted(uf.groups().values(), key=lambda g: (len(g) == 1, g[0]))
