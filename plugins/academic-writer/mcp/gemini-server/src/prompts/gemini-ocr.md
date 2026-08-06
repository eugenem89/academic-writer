<!--
gemini-ocr.md — OCR prompt template for gemini_ocr.

Generalized from ocr_toc_gemini.py's ToC-specific prompt: same "transcribe
faithfully, preserve exact spelling, ignore watermarks" discipline, but for
arbitrary reading-order page text instead of a structured ToC row schema.

Variables filled by gemini_ocr.ts (simple {{var}} substitution, matching the
existing write-section.md convention):
  {{target_language}}      - "he" | "en" | "mixed"
  {{response_format}}      - "concise" | "detailed"
  {{page_numbers}}         - comma-separated list of page numbers in this batch,
                              in the SAME order as the image parts, so the model
                              can align each image to its page_number in the
                              response schema.
  {{rtl_note}}             - filled with RTL guidance when target_language is
                              "he" or "mixed", empty string when "en".
-->

You are transcribing scanned page images from an academic document into
plain reading-order text. This is OCR ONLY: transcribe exactly what is
printed, in the order a human reader would read it. Do NOT correct,
paraphrase, modernize, summarize, or "clean up" the text in any way — if a
word looks garbled, misspelled, or like an OCR artifact in the ORIGINAL
printed page, transcribe it as best you can and flag your uncertainty in the
`notes` field instead of silently fixing it. Correction of OCR output is
handled downstream by a different process; your only job here is faithful
transcription plus honest confidence signaling.

{{rtl_note}}

Target language: {{target_language}}
Response detail level: {{response_format}}

The images you are given correspond, IN ORDER, to these page numbers:
{{page_numbers}}

For EACH image, in the same order, produce one entry with:
  - page_number: the page number this image corresponds to (from the list above)
  - text: the full reading-order plain text of the page, preserving paragraph
    breaks. Do not include running headers/footers/page numbers printed on
    the page unless they are the only content on the page.
  - is_born_digital: always false (these pages were rasterized because they
    lacked a usable text layer; this field exists so the output schema is
    uniform whether or not a page went through Gemini)
  - confidence: "high" | "medium" | "low" — your honest assessment of
    transcription reliability for this page (low-quality scan, faded ink,
    unusual font, heavy annotation/marginalia, etc. should lower this)
  - notes: short free-text flags for anything a downstream editor should
    know: illegible passages (mark their approximate location), watermarks
    or borrower stamps you ignored, footnotes you transcribed separately
    from body text, tables/figures you described instead of transcribing
    verbatim, etc. Empty string if nothing to flag.

{{detail_instructions}}

Ignore watermark/stamp text unrelated to the document's actual content
(e.g. "File # ... belongs to ...", a borrower's name/email, a library
stamp). Do not transcribe those into `text`; you may mention their presence
in `notes` if useful.

Return ONLY the structured JSON matching the provided response schema — no
markdown fences, no commentary outside the schema fields.
