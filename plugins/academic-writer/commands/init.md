---
description: First-time setup for the Academic Writer. Configures researcher profile, analyzes writing style from past articles, indexes research sources, and offers Gemini onboarding. Supports a --quick flag for a fast path. Use on first install, when redoing onboarding from scratch, or when the user wants a quick onboarding (pass --quick).
allowed-tools: [Bash, Read, Write, Glob, Grep, AskUserQuestion, mcp__gemini-api__gemini_raw]
---

# Auto-generated from skills/init/SKILL.md


# Academic Writer — Initialization Wizard

Personalized onboarding that creates your researcher profile, detects available integrations, analyzes your writing style, indexes your research sources, and optionally wires up Gemini as a prose writer.

**Preflight**: If you haven't run `/academic-writer:setup` yet, run that first — it configures your Gemini key and Python tools in a few guided questions.

## Quick Mode

Invoke as `/academic-writer:init --quick` for a fast onboarding path. Quick mode:

- **Runs**: Phase 0 (Preflight), Phase 1 (Integration Detection), Phase 2 (Researcher Profile,
  including the `author_key` step), Phase 3.5 (Gemini Onboarding).
- **Downgrades**: Style Analysis (Phase 2 Step 4) becomes narrative-only — no computational
  extraction, no Hebrew baseline fetch, no `extract-style-metrics.py`, and no Stage 1 voice
  fingerprint chain (voice-miner → voice-distiller → voice-sync). The researcher can still describe
  their style in free text if they wish, but nothing is computed.
- **Skips entirely**: Phase 3 (Research Sources) — `sources` is saved as `[]`.

Everywhere below, a phase or step marked "(skipped in --quick mode)" does not run when `--quick` is
passed. Everything else runs identically in both modes. `--quick` is one way to get a fast
onboarding; `/academic-writer:setup` (see `${CLAUDE_PLUGIN_ROOT}/skills/setup/SKILL.md`) is another
— a friendlier, single-question-at-a-time wizard aimed at non-engineers, covering key setup (with a
live test), Python tooling, and a sample-paragraph checkpoint. Both are standalone and safe to
run any time; use whichever fits — `setup` for the fastest guided path, `init` (full or `--quick`)
for the deeper profile and style analysis.

## The Phases

| Phase | What | Output | Quick mode |
|-------|------|--------|------------|
| 0. Preflight | Create folders, detect existing profile | Workspace ready | Runs |
| 1. Integrations | Auto-detect tools, let you choose | `tools` config | Runs |
| 2. Profile | Field, language, citation style, author_key | Core profile | Runs |
| 3.5. Gemini Onboarding | Optionally enable Gemini as prose writer | `gemini` config | Runs |
| 3. Style Analysis | Read past articles, build fingerprint | `styleFingerprint` + `articleStructure` | Narrative-only, no computation (skipped in --quick mode: computational chain + voice fingerprint chain) |
| 4. Sources | Index Candlekeep library | `sources` array | Skipped entirely in --quick mode |


## Phase 0: Preflight

Run silently before saying anything:

```bash
mkdir -p past-articles .academic-helper .academic-helper/logs && cp -n "${CLAUDE_PLUGIN_ROOT}/thresholds.json" .academic-helper/ 2>/dev/null || true
```

Profile schema, file format, and legacy migration script: see `references/profile-schema.md`.

Check for existing profile:

```bash
cat .academic-helper/profile.md 2>/dev/null && echo "EXISTS" || echo "NOT_FOUND"
```

**If EXISTS**: Use `AskUserQuestion`:

```python
AskUserQuestion(questions=[{
  "question": "You already have an Academic Writer profile. What would you like to do?",
  "header": "Existing profile detected",
  "options": [
    {
      "label": "Update my profile",
      "description": "Keep existing data, modify selected fields only.",
      "markdown": "```\nUpdate Mode\n───────────\n✓ Field of study preserved\n✓ Style fingerprint preserved\n✓ Sources preserved\n→ Re-run only the steps you choose\n```"
    },
    {
      "label": "Start fresh",
      "description": "Delete the current profile and rebuild from scratch.",
      "markdown": "```\nFresh Start\n───────────\n⚠ Existing profile will be replaced\n⚠ Style fingerprint will be cleared\n⚠ Sources will be cleared\n→ Walk through all 4 phases again\n```"
    }
  ],
  "multiSelect": false
}])
```

If **Update**, ask which phases to re-run (multiSelect: true) with options: "Integrations", "Profile (field/language/citation)", "Style Analysis", "Sources". Run only selected phases, then save.

Then greet the user:
> "Welcome to Academic Writer! I'll walk you through setup in a few steps.
>
> Your workspace folders are ready:
> - **`past-articles/`** — drop 5–10 of your published papers here (PDF or DOCX) so I can learn your writing style
> - `.academic-helper/` — your profile (auto-managed)
>
> Let's start."


## Phase 1: Integration Detection

Per-tool detection commands, AskUserQuestion blocks, and port-fallback logic: see `references/integration-setup.md`.

After running detection (parallel batch), store the tool selection as the `tools` object for Phase 4.


## Phase 2: Researcher Profile

### Step 1 of 5 — Full Name & Author Key

Check first whether a `name` field is already present in an existing profile (Phase 0). If not,
ask:

```python
AskUserQuestion(questions=[{
  "question": "What is your full name (as you'd like it to appear on articles)?",
  "header": "Step 1 of 5 — Your Name",
  "options": []
}])
```

Derive `author_key` as a kebab-case slug of the name: lowercase, trim, replace runs of
whitespace/punctuation with a single hyphen, strip leading/trailing hyphens. Example:
"Yotam Fromm" → `yotam-fromm`.

```bash
python3 -c "
import re, sys
name = sys.argv[1]
slug = re.sub(r'[^a-z0-9]+', '-', name.strip().lower()).strip('-')
print(slug)
" "FULL_NAME_HERE"
```

Confirm the derived slug with the user before saving — this key is stable across projects and used
to key cross-project CandleKeep voice-profile lookups (see `${CLAUDE_PLUGIN_ROOT}/skills/voice/voice-sync.sh`), so it
should not change casually later:

```python
AskUserQuestion(questions=[{
  "question": "Your author key will be `DERIVED_SLUG`. This stays stable across all your projects and links your voice profile to your name. Use it, or provide a custom slug?",
  "header": "Confirm author key",
  "options": [
    {"label": "Use `DERIVED_SLUG`", "description": "Recommended — derived automatically from your name."},
    {"label": "I'll provide a custom slug", "description": "You'll type a kebab-case slug of your choice."}
  ],
  "multiSelect": false
}])
```

Store the final value as `author_key`. Store the full name as `name`.


### Step 2 of 5 — Field of Study

```python
AskUserQuestion(questions=[{
  "question": "What is your field of study and area of specialization?",
  "header": "Step 2 of 5 — Field of Study",
  "options": []
}])
```

Show examples below the question:
> "The more specific, the better. Examples:
> - *Early Modern Jewish Philosophy*
> - *Talmudic Literature and Rabbinic Thought*
> - *Medieval Hebrew Poetry*
> - *Biblical Studies — Pentateuch*"

Record the free-text answer as `fieldOfStudy`.


### Step 3 of 5 — Article Language

```python
AskUserQuestion(questions=[{
  "question": "What language will you write your articles in?",
  "header": "Step 3 of 5 — Article Language",
  "options": [
    {
      "label": "Hebrew",
      "description": "Right-to-left, David font, inline-parenthetical citations recommended.",
      "markdown": "```\nHebrew Mode\n───────────\nDirection:  RTL\nFont:       David 11pt\nCitations:  (מחבר, כותרת, עמ' N) in running text\nPurity:     Foreign terms must be transliterated\n```"
    },
    {
      "label": "English",
      "description": "Left-to-right, Times New Roman, Chicago/MLA/APA supported.",
      "markdown": "```\nEnglish Mode\n────────────\nDirection:  LTR\nFont:       Times New Roman 12pt\nCitations:  Chicago, MLA, or APA\n```"
    },
    {
      "label": "Other",
      "description": "You'll specify the language name.",
      "markdown": "```\nOther Language\n──────────────\n→ You'll type the language name\n→ RTL/LTR detected from language\n→ Citation style: your choice\n```"
    }
  ],
  "multiSelect": false
}])
```

Store as `targetLanguage`. If "Other", ask for the language name with a follow-up `AskUserQuestion`.


### Step 4 of 5 — Citation Style

```python
AskUserQuestion(questions=[{
  "question": "Which citation style do you use in your academic work?",
  "header": "Step 4 of 5 — Citation Style",
  "options": [
    {
      "label": "Inline Parenthetical (Recommended for Hebrew)",
      "description": "(Author, Title, Page) in running text — no footnotes required.",
      "markdown": "```\nInline Parenthetical\n────────────────────\nExample:\n  כפי שטוען לוי (לוי, משנת הנפש, עמ' 42), הרעיון\n  המרכזי הוא...\n\nWhen to use:\n  ✓ Hebrew articles\n  ✓ Short citation format\n  ✓ Dense citation density\n```"
    },
    {
      "label": "Chicago / Turabian",
      "description": "Footnotes with full bibliography — most common in English Humanities.",
      "markdown": "```\nChicago / Turabian\n──────────────────\nExample footnote:\n  ¹ Levy, The Soul's Teaching, 42.\n\nWhen to use:\n  ✓ English Humanities articles\n  ✓ History, Philosophy, Literature\n  ✓ Requires bibliography section\n```"
    },
    {
      "label": "MLA",
      "description": "Parenthetical with Works Cited page.",
      "markdown": "```\nMLA\n───\nExample: (Levy 42)\n\nWhen to use:\n  ✓ Literature and language studies\n  ✓ Humanities with Works Cited\n```"
    },
    {
      "label": "APA",
      "description": "(Author, Year) style — more common in social sciences.",
      "markdown": "```\nAPA\n───\nExample: (Levy, 2019, p. 42)\n\nWhen to use:\n  ✓ Social sciences\n  ✓ Psychology, Education, Linguistics\n```"
    }
  ],
  "multiSelect": false
}])
```

Map selection: Inline → `inline-parenthetical`, Chicago → `chicago`, MLA → `mla`, APA → `apa`.


### Step 4b of 5 — Abstract Languages

```python
AskUserQuestion(questions=[{
  "question": "Do your articles need abstracts? Some journals require dual-language abstracts.",
  "header": "Abstract Languages",
  "options": [
    {
      "label": "Primary language only",
      "description": "Abstract in the article's language only.",
      "markdown": "```\nSingle Abstract\n───────────────\nAbstract in: [targetLanguage]\nCommon for: Most journals\n```"
    },
    {
      "label": "Hebrew + English",
      "description": "Dual-language abstracts — common for Israeli journals.",
      "markdown": "```\nDual Abstract\n─────────────\nAbstracts in: Hebrew + English\nCommon for: Israeli journals,\n            academic theses\n```"
    },
    {
      "label": "No abstract needed",
      "description": "Skip abstract generation.",
      "markdown": "```\nNo Abstract\n───────────\nAbstracts will not be generated.\nYou can enable later with\n/academic-writer:init (Update)\n```"
    }
  ],
  "multiSelect": false
}])
```

Store as `abstractLanguages` array:
- Primary only → `["Hebrew"]` (or whatever `targetLanguage` is)
- Hebrew + English → `["Hebrew", "English"]`
- No abstract → `[]`


### Step 5 of 5 — Writing Style

(In `--quick` mode this step still runs, but only the narrative confirm/skip choice — the
computational extraction and Stage 1 voice fingerprint chain below are skipped in --quick mode.)

```python
AskUserQuestion(questions=[{
  "question": "To write articles that sound like you, I need to analyze your past work. Have you added papers to the past-articles/ folder?",
  "header": "Step 5 of 5 — Writing Style",
  "options": [
    {
      "label": "Yes, my papers are ready",
      "description": "Analyze them now to extract your writing fingerprint.",
      "markdown": "```\nStyle Analysis\n──────────────\n→ Reads PDF and DOCX files in past-articles/\n→ Analyzes 25 style dimensions:\n   sentence length, structure, vocabulary,\n   paragraph patterns, transitions, citations,\n   rhetorical moves, tone, intro/conclusion style\n→ Shows you the fingerprint before saving\n→ You can correct anything before it's stored\n```"
    },
    {
      "label": "Skip for now",
      "description": "Profile will be saved without a style fingerprint. Articles will use generic academic style.",
      "markdown": "```\nSkip Style Analysis\n───────────────────\n⚠ Articles won't match your voice yet\n→ Add papers to past-articles/ anytime\n→ Re-run: /academic-writer:init\n   (choose 'Update' → 'Style Analysis')\n```"
    }
  ],
  "multiSelect": false
}])
```

**If "Yes, my papers are ready"**, run:

```bash
ls past-articles/
```

**(skipped in --quick mode)** The Computational extraction step and the Stage 1 voice fingerprint
chain below do not run in `--quick` mode. In quick mode, do only a lightweight narrative pass:
read a couple of files and describe style qualitatively (categories D, F, G below), then save that
narrative under `## Style Fingerprint` in Phase 4 as free text instead of the full JSON object.

**Step 1: Computational extraction** — Run the metrics extraction script to get hard numbers.

**Optional, best-effort, Hebrew only:** if `targetLanguage` is Hebrew, first try to fetch the
**shared Hebrew baseline** from CandleKeep for a contrastive score (item titled *Hebrew Linguistic
Reference*, mirrored on GitHub at
[yodem/hebrew-linguistics-data](https://github.com/yodem/hebrew-linguistics-data); the same item is
read by the `hebrew-book-producer` plugin so both share one source of truth). **Skip this whole
step if `targetLanguage` is not Hebrew, OR if `tools.candlekeep.enabled` is false, OR if no
CandleKeep CLI/tool is present** — the baseline is a nice-to-have contrastive signal, not a
requirement, and the extractor runs fine without it (see below). Look it up by exact title rather
than a hardcoded id — ids can drift if the item is ever recreated, and there is no fallback id to
fall back to:

```bash
mkdir -p .ctx
BASELINE_TITLE="Hebrew Linguistic Reference"
BASELINE_ID=$(ck items list --json 2>/dev/null | jq -r --arg t "$BASELINE_TITLE" '[.[] | select(.title == $t)] | if length == 1 then .[0].id elif length > 1 then (sort_by(.id) | .[0].id) else empty end')
if [ -n "$BASELINE_ID" ]; then
  ck items get "$BASELINE_ID" > .ctx/hebrew-linguistic-reference.md
else
  echo "Could not find CandleKeep item titled '$BASELINE_TITLE' by exact title match — continuing without a contrastive baseline (non-fatal)."
  echo "If you want contrastive scoring, search CandleKeep manually (ck items list --json | jq) and rename the item to match exactly, or re-run init after adding it."
fi
```

Then run the extractor. Pass `--baseline`/`--contrastive` only when the baseline file above was
successfully fetched — the extractor degrades gracefully and simply omits the contrastive section
when no baseline is present, so this is safe to skip entirely for non-Hebrew articles or when
CandleKeep isn't configured:

```bash
if [ -f .ctx/hebrew-linguistic-reference.md ]; then
  BASELINE_ARGS="--baseline .ctx/hebrew-linguistic-reference.md --contrastive"
else
  BASELINE_ARGS=""
fi
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/extract-style-metrics.py \
  --input past-articles/ \
  --aggregate \
  $BASELINE_ARGS \
  --json \
  --output /tmp/style-metrics.json
```

The extractor reads the baseline JSON code block embedded in the `08-style-fingerprint-baseline` chapter of the cached markdown, so there is no separate JSON file in the plugin's `references/` folder.

Read the results:
```bash
cat /tmp/style-metrics.json
```

This gives you 30+ numerical metrics (sentence length, passive voice, transitions, etc.) and contrastive scores showing what's distinctive about this researcher vs. baseline academic Hebrew. It also includes a `frequentTerms` field — the researcher's own top-N high-frequency content vocabulary (count/length controlled by `thresholds.json > typography.styleMetrics.topFrequentTermsCount` / `minTermLength`). Keep `frequentTerms` in the fingerprint object as-is when you assemble the `## Style Fingerprint` JSON block in Phase 4 below — it steers the section-writer toward the researcher's own established terminology instead of generic phrasing (see `style-fingerprint-rubric.md § Preferred Terminology`).

**Step 2: Text extraction for qualitative analysis** — For each file, extract text mechanically:
- PDF: `python3 -c "import sys; import pdfplumber; [print(p.extract_text()) for p in pdfplumber.open(sys.argv[1]).pages]" past-articles/FILENAME`. **If this fails** (pdfplumber not installed, or extraction errors), do NOT fall back to a crude `strings`-style byte extraction — it produces garbled, unreliable text. Instead skip that file for the qualitative pass, note it as skipped, and continue with the rest of the corpus.
- DOCX: `python3 -c "import docx; d=docx.Document('past-articles/FILENAME'); [print(p.text) for p in d.paragraphs]" 2>/dev/null`

**Step 3: Qualitative analysis** — Read the text and computational metrics. Analyze across the qualitative dimensions (C–I below) that the script cannot compute: paragraph formula, tone, rhetorical patterns, templates, representative excerpts.

Show the combined fingerprint summary (computational + qualitative) and confirm before saving:

```python
AskUserQuestion(questions=[{
  "question": "Here's the writing fingerprint I extracted. Is this accurate?",
  "header": "Style fingerprint review",
  "options": [
    {"label": "Looks good — save it", "description": "Profile will be saved with this fingerprint."},
    {"label": "I'd like to adjust some things", "description": "Tell me what to change and I'll update before saving."}
  ],
  "multiSelect": false
}])
```

### 25-Dimension Style Analysis

Full rubric (all 30 dimensions across 8 categories A–I): see `references/profile-schema.md`.


### Stage 1 voice fingerprint

**(skipped in --quick mode)**

After past-articles are scanned, invoke the `voice-miner` agent:

1. Run `voice-miner` agent on `past-articles/`. Output is `.voice/fingerprint.md`.
2. **Check for `NEEDS CORPUS`** before proceeding:
   ```bash
   grep -q "NEEDS CORPUS" .voice/fingerprint.md && echo "STUB" || echo "VALID"
   ```
   If `STUB`: skip steps 3–5 below entirely and tell the user: "Not enough past articles yet for a
   voice fingerprint (need at least `thresholds.json: voice.corpus.minArticles` articles /
   `voice.corpus.minTotalWords` words — see `${CLAUDE_PLUGIN_ROOT}/thresholds.json`). Add more to `past-articles/` and
   re-run `/academic-writer:init`, or skip voice for now." Then continue to Phase 3.5/Phase 3
   without a voice fingerprint.
3. If `VALID`: run `voice-distiller --from-fingerprint` to seed the four-section
   `AUTHOR_VOICE.md` at root.
4. **Check that `AUTHOR_VOICE.md` was actually produced** before syncing:
   ```bash
   [ -s AUTHOR_VOICE.md ] && echo "PRESENT" || echo "MISSING"
   ```
   If `MISSING`: print "voice-distiller did not produce AUTHOR_VOICE.md — skipping voice-sync push.
   Re-run voice-miner/voice-distiller manually once past-articles/ has enough content." and skip
   step 5.
5. If `PRESENT`: run `voice-sync push` (this requires `author_key` to already be saved in
   `.academic-helper/profile.md` — see Phase 4 below; run Phase 4 first if needed, or rely on
   voice-sync's own loud failure if `author_key` is missing).
6. Print: "✓ Voice fingerprint created from N past articles. You can write articles now, or run
   `/academic-writer:voice` for a deeper profile (recommended)."

The user is not required to run Stage 2. They can start writing immediately with the fingerprint.


## Phase 3.5: Gemini Onboarding

Runs in both full and `--quick` modes. Ask the researcher whether to enable Gemini as the prose
writer for `/write`, `/edit`, and `/edit-section`. Claude remains the orchestrator and citation
auditor either way.

```python
AskUserQuestion(questions=[{
  "question": "Enable Gemini as the prose writer? Claude stays in charge of orchestration and citation audits — Gemini drafts and self-reviews paragraphs.",
  "header": "Optional — Gemini integration",
  "options": [
    {
      "label": "Yes, enable Gemini",
      "description": "Requires a Google AI Studio API key (free tier available).",
      "markdown": "```\nGemini ON\n─────────\n→ Faster, lower-cost drafting\n→ Per-language calibration gate runs\n   on first /write in each language\n→ Auditor still runs on Claude\n```"
    },
    {
      "label": "No, Claude only",
      "description": "Today's behavior — Claude writes and reviews everything.",
      "markdown": "```\nClaude only\n───────────\n→ No external API needed\n→ You can enable Gemini later via init\n```"
    }
  ],
  "multiSelect": false
}])
```

### If "No, Claude only"

Skip the rest of this phase. Note in summary that Gemini is disabled.

### If "Yes, enable Gemini"

#### Step 3.5.a — Check for existing key

```bash
if [ -n "$GOOGLE_API_KEY" ]; then
  echo "Found GOOGLE_API_KEY in environment."
elif [ -f .academic-helper/secrets.json ] && python3 -c "import json,sys; sys.exit(0 if json.load(open('.academic-helper/secrets.json')).get('GOOGLE_API_KEY') else 1)" 2>/dev/null; then
  echo "Found GOOGLE_API_KEY in .academic-helper/secrets.json."
else
  echo "NO_KEY"
fi
```

#### Step 3.5.b — If NO_KEY, walk through key creation

> "To get a Google AI Studio API key:
> 1. Open https://aistudio.google.com/apikey in your browser
> 2. Sign in with a Google account
> 3. Click 'Create API key' — copy the key (it begins with `AIza...`)
> 4. Free tier covers typical academic-writer usage."

Ask how to store the key:

```python
AskUserQuestion(questions=[{
  "question": "Where should I store your Gemini API key?",
  "header": "Key storage",
  "options": [
    {
      "label": "Environment variable (recommended)",
      "description": "Set GOOGLE_API_KEY in your shell profile. Survives across projects.",
      "markdown": "```\nexport GOOGLE_API_KEY=\"AIza...\"\n# add to ~/.zshrc or ~/.bashrc\n```"
    },
    {
      "label": "Project-local secrets file",
      "description": ".academic-helper/secrets.json (gitignored, this project only).",
      "markdown": "```\n.academic-helper/secrets.json\n──────────────────────────────\n{ \"GOOGLE_API_KEY\": \"AIza...\" }\n→ Already in .gitignore\n```"
    }
  ],
  "multiSelect": false
}])
```

- **Env var path**: print the export command for the user to run. Then ask them to confirm they've set it and reopened the session so Claude Code picks up the env. You cannot set their shell env from inside Claude Code.
- **Secrets file path**: ask them to paste the key, then:

```bash
mkdir -p .academic-helper
python3 -c "
import json, pathlib, os
p = pathlib.Path('.academic-helper/secrets.json')
data = json.loads(p.read_text()) if p.exists() else {}
data['GOOGLE_API_KEY'] = os.environ['_PASTED_KEY']
p.write_text(json.dumps(data, indent=2))
import stat
p.chmod(stat.S_IRUSR | stat.S_IWUSR)
"
```

(Pass the pasted key via env var to avoid leaking it through shell history.) Confirm `.academic-helper/secrets.json` is gitignored.

#### Step 3.5.c — Probe the key

Run a one-shot probe through the MCP server to verify the key works end-to-end:

```
mcp__gemini-api__gemini_raw({
  system: "Reply with exactly the word PONG and nothing else.",
  prompt: "PING"
})
```

- On success (returned `text` contains "PONG"): print "✓ Gemini API key verified."
- On `{ error: { code: "no_credentials" } }`: print "Key not detected by the MCP server. If you just set the env var, restart Claude Code so the server inherits it. Re-run `/academic-writer:init` after restart."
- On any other error: print the error and tell the user Gemini will not be available until resolved.

#### Step 3.5.d — Note the calibration gate

> "On your first `/academic-writer:write` in each language, a calibration gate will run:
> - You'll see one Claude paragraph and one Gemini paragraph on the same topic
> - You approve or reject Gemini for that language
> - Approved languages are stored in your profile under `gemini.approvedLanguages`."

#### Step 3.5.e — Store Gemini settings

The `## Gemini` block in `profile.md` (written in Phase 4 below) will include:

```json
{
  "enabled": true,
  "approvedLanguages": [],
  "models": {}
}
```

If the researcher chose "No, Claude only": `enabled: false`, no `approvedLanguages`.


## Phase 3: Research Sources

**(skipped entirely in --quick mode — `sources` is saved as `[]`)**

**If Candlekeep is enabled:**

```python
AskUserQuestion(questions=[{
  "question": "Let's index your research library. Have you added sources to Candlekeep yet?",
  "header": "Research sources",
  "options": [
    {
      "label": "Yes, index my sources now",
      "description": "I'll enrich and index everything in your Candlekeep library.",
      "markdown": "```\nSource Indexing\n───────────────\n→ Lists all items in your library\n→ Runs ck items enrich on each\n   (extracts title, author, TOC)\n→ Saves minimal metadata to profile\n   (id, title, type only)\n```"
    },
    {
      "label": "Skip — I'll add sources later",
      "description": "Run /academic-writer:init again (choose Update → Sources) after adding items.",
      "markdown": "```\nSkip Sources\n────────────\n⚠ Articles won't have source metadata yet\n→ Add sources with: ck items add file.pdf\n→ Then re-run this step\n```"
    }
  ],
  "multiSelect": false
}])
```

If **"Yes"**: list and enrich all items:

```bash
ck items list --json
```

For each item ID:
```bash
ck items enrich ITEM_ID
```

Tell the researcher: "Enriching your sources — extracting titles, authors, and table of contents from each document. This may take a moment..."

After enrichment, re-list and build the sources array (id + title + type only — never raw JSON).

**If Candlekeep is NOT enabled**: set sources to `[]`.


## Phase 4: Save Profile + Register Workflows

Use the Write tool to save `.academic-helper/profile.md`:

```markdown
# Academic Writer Profile

name: FULL_NAME_HERE
author_key: kebab-case-slug
fieldOfStudy: FIELD_HERE
citationStyle: CITATION_STYLE_HERE  # e.g. inline-parenthetical, chicago, mla, apa
targetLanguage: TARGET_LANGUAGE_HERE  # e.g. Hebrew, English, ... (whatever the researcher chose in Phase 1)
abstractLanguages:
  - ABSTRACT_LANGUAGE_HERE  # one entry per language chosen in Phase 1 (e.g. Hebrew, or Hebrew + English for a dual abstract)
analyzedArticles: []
createdAt: ISO_TIMESTAMP
updatedAt: ISO_TIMESTAMP

## Tools

```json
{
  "candlekeep": { "enabled": true },
  "notebooklm": { "enabled": false }
}
` ` `

## Output Format Preferences

```json
` ` `

## Style Fingerprint

```json
{ ... full 25-dimension fingerprint object, including computationalMetrics.frequentTerms from Step 1's extractor output when computational extraction ran ... }
` ` `

## Article Structure

```json
{ ... article structure object ... }
` ` `

## Sources

```json
[]
` ` `

## Gemini

```json
{
  "enabled": true,
  "approvedLanguages": [],
  "models": {}
}
` ` `
```

(Replace ` ` ` with actual backtick triplets when writing the file.) `## Gemini` reflects the
outcome of Phase 3.5: `enabled: false` (no `approvedLanguages`/`models` keys) if the researcher
chose "No, Claude only".



## Completion

```python
AskUserQuestion(questions=[{
  "question": "Setup is complete. What would you like to do next?",
  "header": "You're all set!",
  "options": [
    {
      "label": "Write my first article",
      "description": "Launch /academic-writer:write to start writing.",
      "markdown": "```\nWrite Article\n─────────────\n→ /academic-writer:write\n→ Conversational pipeline:\n   subject → sources → thesis\n   → outline → write → .docx\n```"
    },
    {
      "label": "Check system health",
      "description": "Run /academic-writer:health to verify everything is working.",
    },
    {
      "label": "I'm done for now",
      "description": "Profile saved. Run /academic-writer:write anytime to start writing.",
      "markdown": "```\nProfile saved to:\n  .academic-helper/profile.md\n\nKey commands:\n  /academic-writer:write         ← write an article\n  /academic-writer:health  ← check everything\n  /academic-writer:update-tools ← change integrations\n```"
    }
  ],
  "multiSelect": false
}])
```

Show a summary table:

> | Setting | Value |
> |---------|-------|
> | Field | [field] |
> | Language | [language] |
> | Citation style | [style] |
> | Style fingerprint | ✓ Analyzed / — Skipped |
> | Sources indexed | [N] documents |
> | Tools enabled | [list] |
