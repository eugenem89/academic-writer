#!/usr/bin/env python3
"""
Stage 00 — inventory the source libraries and make a frozen working copy.

Nothing downstream ever touches an original file. This stage walks the folder
of libraries, hashes every file, works out what can be read and how, and
(by default) copies everything into a working directory that the rest of the
pipeline treats as read-only truth.

    python3 00_inventory.py --root "/path/to/EndNote libraries" --work ./work

Google Drive note: do not run the SQLite reader against a `.enl` that lives in
a syncing Drive/Dropbox folder. The sync client can swap the file mid-read and
SQLite will report corruption on a perfectly good library. Copy first — which
is exactly what this stage does.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone

SQLITE_MAGIC = b"SQLite format 3\x00"
CLOUD_HINTS = ("google drive", "googledrive", "cloudstorage", "dropbox",
               "onedrive", "icloud", "box sync")


def sha256(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def classify(path: str) -> tuple[str, str]:
    """Returns (kind, note). kind is one of: enl, enl-legacy, endnote-xml, ris, skip."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".enl":
        try:
            with open(path, "rb") as fh:
                head = fh.read(16)
        except OSError as exc:
            return "skip", f"unreadable: {exc}"
        if head == SQLITE_MAGIC:
            return "enl", "EndNote X7+ SQLite library"
        return "enl-legacy", ("pre-X7 binary library — cannot be read directly; "
                              "open in EndNote and File > Export as XML")
    if ext == ".enlx":
        return "skip", "compressed library — unzip it first, then re-run inventory"
    if ext == ".xml":
        try:
            with open(path, "rb") as fh:
                head = fh.read(4096).lower()
        except OSError as exc:
            return "skip", f"unreadable: {exc}"
        if b"<records>" in head or b"<record>" in head or b"endnote" in head:
            return "endnote-xml", "EndNote XML export"
        return "skip", "XML but not an EndNote export"
    if ext in (".ris", ".txt"):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                head = fh.read(2048)
        except OSError as exc:
            return "skip", f"unreadable: {exc}"
        if "TY  - " in head or "\nER  -" in head:
            return "ris", "RIS export (lossy — custom fields may be missing)"
        return "skip", "text file, not RIS"
    return "skip", ""


def unique_library_name(stem: str, taken: set[str]) -> str:
    name = stem
    i = 2
    while name in taken:
        name = f"{stem}-{i}"
        i += 1
    taken.add(name)
    return name


def main() -> int:
    ap = argparse.ArgumentParser(description="Inventory EndNote libraries.")
    ap.add_argument("--root", required=True, help="folder containing the libraries")
    ap.add_argument("--work", default="./work", help="working directory (default ./work)")
    ap.add_argument("--no-copy", action="store_true",
                    help="inventory only; do not make the frozen working copy")
    ap.add_argument("--include-data-folders", action="store_true",
                    help="also copy the .Data attachment folders (large)")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    work = os.path.abspath(args.work)
    sources_dir = os.path.join(work, "sources")
    os.makedirs(sources_dir, exist_ok=True)

    entries: list[dict] = []
    data_folders: list[dict] = []
    taken: set[str] = set()

    for dirpath, dirnames, filenames in os.walk(root):
        for d in list(dirnames):
            if d.endswith(".Data"):
                full = os.path.join(dirpath, d)
                pdfs = sum(len([f for f in fs if f.lower().endswith(".pdf")])
                           for _, _, fs in os.walk(full))
                total = sum(len(fs) for _, _, fs in os.walk(full))
                data_folders.append({"path": full, "files": total, "pdfs": pdfs})
                dirnames.remove(d)
        for filename in sorted(filenames):
            full = os.path.join(dirpath, filename)
            kind, note = classify(full)
            if kind == "skip" and not note:
                continue
            stat = os.stat(full)
            entry = {
                "path": full,
                "relpath": os.path.relpath(full, root),
                "kind": kind,
                "note": note,
                "bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "sha256": sha256(full) if stat.st_size < (2 << 30) else "",
            }
            if kind in ("enl", "endnote-xml", "ris"):
                entry["library"] = unique_library_name(
                    os.path.splitext(filename)[0], taken)
                lower = full.lower()
                if kind == "enl" and any(h in lower for h in CLOUD_HINTS):
                    entry["warning"] = ("lives in a cloud-synced folder; the pipeline "
                                        "reads the frozen copy, never this file")
            entries.append(entry)

    readable = [e for e in entries if e["kind"] in ("enl", "endnote-xml", "ris")]
    blocked = [e for e in entries if e["kind"] not in ("enl", "endnote-xml", "ris")]

    if not args.no_copy:
        for entry in readable:
            dest = os.path.join(sources_dir, f"{entry['library']}{os.path.splitext(entry['path'])[1]}")
            shutil.copy2(entry["path"], dest)
            entry["frozen_copy"] = dest
            if sha256(dest) != entry["sha256"]:
                print(f"ERROR: copy of {entry['path']} does not match source hash",
                      file=sys.stderr)
                return 2
        if args.include_data_folders:
            for folder in data_folders:
                dest = os.path.join(sources_dir, os.path.basename(folder["path"]))
                if not os.path.exists(dest):
                    shutil.copytree(folder["path"], dest)
                folder["frozen_copy"] = dest

    inventory = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "root": root,
        "work": work,
        "libraries": readable,
        "not_readable": blocked,
        "data_folders": data_folders,
    }
    out = os.path.join(work, "inventory.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(inventory, fh, ensure_ascii=False, indent=2)

    print(f"Inventory written to {out}")
    print(f"  readable libraries : {len(readable)}")
    for entry in readable:
        warn = f"  [!] {entry['warning']}" if entry.get("warning") else ""
        print(f"    - {entry['library']:<32} {entry['kind']:<12} "
              f"{entry['bytes']/1e6:8.1f} MB{warn}")
    if blocked:
        print(f"  needs manual export: {len(blocked)}")
        for entry in blocked:
            print(f"    - {entry['relpath']}: {entry['note']}")
    if data_folders:
        total_pdfs = sum(d["pdfs"] for d in data_folders)
        print(f"  .Data folders      : {len(data_folders)} ({total_pdfs} PDFs)")
        if not args.include_data_folders:
            print("    (not copied — pass --include-data-folders to freeze them too)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
