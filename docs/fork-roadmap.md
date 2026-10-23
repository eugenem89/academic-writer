# Fork Roadmap: Pi Academic for Eugene Matanky

Status: proposal. Nothing below has been implemented yet; each item is a separate,
reviewable change. Upstream: `JackMatanky/pi-academic` (formerly `pi-academic-writer`).

## What to keep

The package is already careful in ways that most AI writing tools are not:

- Evidence is staged. Candidate notes start unverified, the outline is approved by
  the researcher, the approved evidence is frozen per article, and every section
  is written from that frozen snapshot.
- Citation keys are never invented. The audit blocks export on a missing key or a
  malformed marker, and it says plainly that it does not prove a claim.
- Tool output that is advisory (lint, reverse outline, outline diagnostics) is
  labelled as advisory and never treated as a judgment.
- Source text is quarantined as data, not instructions.

The changes below build on these guarantees and do not loosen them.

## Proposed changes, in priority order

### 1. Fork hygiene (small)

- Point the README install commands, `package.json` `repository`, and the Support
  links at the fork. Keep `upstream` as a second remote so upstream fixes can be
  merged.
- `.github/workflows/release.yml` bumps the version and tags a release on every
  push to `main`. Disable it on the fork, or run it only for tags, so that
  personal commits do not produce releases.

### 2. Bring your own reference library (medium)

At present a source can enter `sources.json` in only two ways: as a Zotero item, or
as a file ingested from `.pi-academic/sources/`. A researcher whose library is in
Citavi or EndNote has no way to bring it in.

- Add an import tool, `pi_academic_import_bibliography`. It reads a
  project-relative BibTeX (or CSL-JSON) export and merges its entries into
  `sources.json` and `bibliography.bib`.
  - It keeps the citation keys from the export, and it never overwrites a key that
    is already in the registry.
  - It reports duplicates and conflicts instead of guessing between them, in the
    same spirit as `relink`.
  - Citavi can export BibTeX with stable keys. EndNote can export through RIS,
    then BibTeX.
- Add a third `sourceType` (for example `"library"`), whose identity is
  `library:<exportName>:<citeKey>`.
  - The identity rules live in only three files: `citations/source-records.ts`,
    `citations/source-registry.ts` and `research/notes.ts`. This keeps the change
    contained.
  - A note can cite a library record only when its quote has also been checked
    against the source's full text. Bibliographic metadata alone is not evidence.
- Why it comes first: everything else depends on it. RAG hits have to map to a
  stable citation key, and that key needs a home in `sources.json`.

### 3. Hebrew in the citeproc path (medium)

`AGENTS.md` records a known gap: citeproc DOCX export (Chicago notes, and so on)
does not apply Hebrew right-to-left (RTL) post-processing. Only the
literal-citation generator does. For bilingual Jewish Studies work, this is the
main gap.

- Apply the RTL handling that the literal-citation generator already has to citeproc
  DOCX output when `lang` is `he`. The step should run over paragraphs and
  footnotes, and it should leave Latin-script runs left-to-right.
- Hebrew bibliography conventions. Support the two conventions already used in
  this library:
  - an English title, plus `language = {Hebrew}`, rendered with "(in Hebrew)";
  - a transliterated title, with no language tag.
- Add a Hebrew-locale CSL check to `pi_academic_health`, covering `שם`/ibid. and
  Hebrew ordinal and term localisation.
- Add a test fixture: a Hebrew article with mixed-script footnotes, exported to
  DOCX, with direction marks checked in `document.xml`.

### 4. Canonical locators for classical sources (small to medium)

Notes and locators assume page numbers, plus the Pandoc locator terms (folio,
verse, section, line). Rabbinic and kabbalistic sources are cited by canonical
reference:

- Talmud: b. Ber. 2a
- Zohar: 1:15a
- Mishneh Torah: Hil. Teshuvah 3:4
- Manuscripts: MS Parma 1221, fol. 12r

The proposed changes are:

- Add an optional `canonicalRef` to research notes, alongside `pdfPageIndex`. The
  Sefaria step can fill it, because Sefaria refs are already canonical.
- Teach the writer and the audit to emit and accept these references as locators,
  for example `[@zohar, 1:15a]`, without treating them as malformed page numbers.

### 5. Retrieval (RAG) integration (needs the details of the index; see below)

`docs/rag-todo.md` and `docs/removed-rag-information.md` show that upstream
removed an earlier RAG design. That design let "page numbers from RAG" through
without verification. The proposal is to connect to an external index without
reopening that hole.

- Connect to the index as an MCP server, the way Zotero and Sefaria are connected
  now. No index code goes into this package.
- Give it a small contract:
  - `search(query, filters)` returns passages with
    `{ sourceKey, locator, text, score }`;
  - `get_passage(id)` returns the exact text, with its locator.
- Record it in the profile as `tools.rag.enabled`, with an optional
  `tools.rag.server` and scope. Credentials stay in the MCP config, as for
  Zotero.
- The researcher agent may use RAG hits only to create unchecked candidate
  notes, with `retrievedVia: "rag"`. A candidate becomes verified only after its
  quote and locator have been confirmed against the full text, from Zotero, a
  local file or Sefaria. This is the existing verification gate, unchanged.
- Map `sourceKey` to the citation keys in `sources.json` (item 2). A hit that does
  not map to a source is reported as a gap, never cited.
- Add a health check: whether the server is reachable, the tools exist, and a
  sample query maps to a known key.

### 6. Pacing and cost (small)

Section writing dispatches one writer subagent per section, then runs a
per-paragraph pipeline. On a usage-capped plan, a long article can use up a
five-hour window. The proposed changes are:

- Add a `writing.concurrency` profile field: 1 means sequential.
- Add a pre-flight estimate (sections × paragraphs × checks), shown before
  dispatch.

## Questions for the RAG / indexing side

These are needed before item 5 can be specified:

1. What is indexed? Book PDFs, articles, notes, manuscripts? Which languages? Is
   the Hebrew text OCR'd?
2. Where does the index live? Is it an OpenAI vector store, local Chroma or FAISS,
   or another service? Is it reachable from this machine without ChatGPT?
3. How is a chunk tied to its source and page? Does each chunk carry a stable
   source ID (a Citavi or EndNote ID, a DOI, a filename) and a page or locator?
4. Is there already an API or script for querying it (Python, an HTTP endpoint)?
   Is there already an MCP server?
5. How large is it (number of documents and chunks), and how often is it
   updated?
