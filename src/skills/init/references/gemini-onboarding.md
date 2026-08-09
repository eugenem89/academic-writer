# Gemini Onboarding Detail (Phase 3.5)

> Read this when you reach Phase 3.5 (Gemini Onboarding) in SKILL.md. It has the full key-check,
> key-creation, live-probe, and settings-storage procedure.

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

The `## Gemini` block in `profile.md` (written in Phase 4) will include:

```json
{
  "enabled": true,
  "approvedLanguages": [],
  "models": {}
}
```

If the researcher chose "No, Claude only": `enabled: false`, no `approvedLanguages`.
