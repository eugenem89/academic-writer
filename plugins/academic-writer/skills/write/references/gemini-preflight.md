# Gemini Pre-Flight Detail

> Read this when you reach the "Gemini pre-flight" step in SKILL.md — immediately after the voice
> profile load, before Step 1 (Subject & Language) finishes and before any agent is spawned.

## Gemini pre-flight (immediately after voice profile load)

Determine which model runs the prose for this article and whether a calibration gate must fire first.

1. Read the approved-language list from the profile:

```bash
python3 -c "
import re, json
content = open('.academic-helper/profile.md').read() if __import__('os').path.exists('.academic-helper/profile.md') else ''
m = re.search(r'## Gemini\n+\x60\x60\x60json\n(.*?)\n\x60\x60\x60', content, re.DOTALL)
data = json.loads(m.group(1)) if m else {}
print(json.dumps(data.get('approvedLanguages', [])))
"
```

2. Detect whether a Gemini key is available:

```bash
if [ -n "$GOOGLE_API_KEY" ]; then
  echo "GEMINI_KEY: env"
elif [ -f .academic-helper/secrets.json ] && python3 -c "import json,sys; sys.exit(0 if json.load(open('.academic-helper/secrets.json')).get('GOOGLE_API_KEY') else 1)" 2>/dev/null; then
  echo "GEMINI_KEY: file"
else
  echo "GEMINI_KEY: missing"
fi
```

3. Decide the path. After Step 1 of Phase 1 captures `targetLanguage`:

| GEMINI_KEY | targetLanguage in approvedLanguages | Action |
|---|---|---|
| missing | n/a | Warn once: "No Gemini key configured. Running on Claude. Run `/academic-writer:setup` to enable Gemini." Set `geminiMode = "claude-only"`. Proceed. |
| present | yes | Set `geminiMode = "gemini"`. Proceed. |
| present | no | **Invoke voice-calibrator with `--compare-models {targetLanguage}` BEFORE continuing.** Wait for its `approved | rejected | error` status. On `approved` set `geminiMode = "gemini"`; on `rejected` set `geminiMode = "claude-only"` for this session (don't ask again this run); on `error` warn once and set `geminiMode = "claude-only"`. |

Persist the chosen mode in `.academic-helper/session-state.json` so subagents and later steps see the same decision:

```bash
mkdir -p .academic-helper
python3 -c "
import json, pathlib
p = pathlib.Path('.academic-helper/session-state.json')
state = json.loads(p.read_text()) if p.exists() else {}
state['geminiMode'] = '$GEMINI_MODE'
state['geminiFallback'] = state.get('geminiFallback', False)
p.write_text(json.dumps(state, indent=2))
"
```

The calibration gate must run **after** Step 1 (Subject & Language) but **before** Step 3 (Deep Read) — i.e., as soon as `targetLanguage` is known and before any agent is spawned. If it runs at any other point, it cannot influence section-writer or synthesizer.

## Mid-run Gemini failure handler

The first time any MCP tool call (`gemini_write_section`, `gemini_synthesize`, `gemini_edit`, `gemini_calibrate_sample`) returns a structured error during this `/write` run, ask the user **once** using AskUserQuestion:

> "Gemini failed: {error.message}. Continue this article on Claude, or abort and retry later?"

Options: `Continue on Claude` | `Abort`.

- On **Continue on Claude**: set `.academic-helper/session-state.json > geminiFallback: true`. Subsequent MCP failures during this run respect the choice — do NOT re-ask. Subagents spawned after this point receive `geminiFallback: true` in their prompt; section-writer and synthesizer skip the Gemini path and use their fallback branches.
- On **Abort**: stop the pipeline cleanly; do NOT write a partial DOCX.

If `geminiFallback` is already `true` at the start of the run (carried over from a prior run in the same session), skip the question entirely and run subagents in fallback mode from the start.
