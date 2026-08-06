---
name: setup
description: "Deprecated internal alias for quick onboarding. Superseded by /academic-writer:init --quick. Not user-invocable; kept only as documentation for anyone who still references it."
user-invocable: false
allowedTools: [Bash, Read, Write, Glob, Grep, AskUserQuestion, mcp__gemini-api__gemini_raw]
metadata: {author: "Yotam Fromm", version: "0.3.0"}
---

# Academic Writer Setup (deprecated wrapper)

This skill is **internal and deprecated**. It used to be a separate quick-onboarding path with its
own duplicated phase bodies (profile, integrations, Gemini onboarding, optional style fingerprint).
Those phases have been consolidated into `init` to remove drift between the two skills.

## Use instead

```
/academic-writer:init --quick
```

See `${CLAUDE_PLUGIN_ROOT}/skills/init/SKILL.md`'s **"## Quick Mode"** section for exactly what quick mode runs and
skips: it runs Preflight, Integration Detection, Profile (including the `author_key` step), and
Gemini Onboarding; it downgrades Style Analysis to narrative-only; it skips Research Sources
entirely.

## Why this file still exists

Kept as a discoverability breadcrumb and to preserve the skill id in case any external reference
(docs, muscle memory) still points at `setup`. It is not registered as a slash command
(`user-invocable: false`) and has no phase logic of its own — do not add any here. All onboarding
logic lives in `${CLAUDE_PLUGIN_ROOT}/skills/init/SKILL.md`.
