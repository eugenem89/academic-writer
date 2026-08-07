# Python Dependency Check (setup Step 4)

> Loaded on demand by `setup` Step 4.

Academic Writer's Python-side scripts (style-metrics extraction, DOCX export, PDF/DOCX text
reading) rely on four packages. Import names differ from package names for two of them — note
`pymupdf` installs as the package `pymupdf` but imports as `fitz`.

| Package (pip install name) | Import name | Used for |
|---|---|---|
| `python-docx` | `docx` | Reading/writing `.docx` files |
| `lxml` | `lxml` | XML parsing backing `python-docx` |
| `pdfplumber` | `pdfplumber` | Extracting text from PDFs |
| `pymupdf` | `fitz` | PDF rendering/OCR-adjacent handling |

## Check script

Run once, idempotent, safe to re-run:

```bash
python3 -c "
import importlib
mods = {'python-docx': 'docx', 'lxml': 'lxml', 'pdfplumber': 'pdfplumber', 'pymupdf': 'fitz'}
missing = []
for pkg, mod in mods.items():
    try:
        importlib.import_module(mod)
    except ImportError:
        missing.append(pkg)
if missing:
    print('MISSING:' + ','.join(missing))
else:
    print('ALL_PRESENT')
"
```

## Install command

If the check reports `MISSING:...`, install everything in one shot (installing all four is fine
even if only some are missing — idempotent, no harm re-installing present ones):

```bash
pip3 install python-docx lxml pdfplumber pymupdf
```

If `pip3` is not found, try `python3 -m pip install python-docx lxml pdfplumber pymupdf`.

## Known gap: no requirements.txt

There is no `requirements.txt`, `pyproject.toml`, or any other Python dependency manifest anywhere
in this repo — these four packages are only ever referenced ad hoc, inline, in skill scripts. This
setup wizard's check-and-install step is currently the only place dependency installation is
walked through interactively. Not a blocker, just a gap worth knowing about if you're debugging a
"module not found" error outside of this wizard (e.g. running `extract-style-metrics.py` directly).
