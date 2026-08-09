# Changelog

All notable changes to the academic-writer plugin are documented here.

## [0.6.0] — 2026-08-09

Audit-gap closure release. Everything below came out of the 2026-08-05→06 plugin
audit and the follow-up gap sweep.

### Added

- **`/academic-writer:ocr`** — the bundled `gemini_ocr` MCP tool finally has a
  user-facing entry point. Takes a PDF/image or a directory of them, calls the
  tool sequentially (never batched), follows the tool's own 40-page truncation
  loop, and writes to `ocr-output/<basename>.ocr.md`. Degrades honestly on files
  over 20MB, since the Files-API upload path is still a genuine `TODO` in the
  server.
- **Secure credential configuration** — the Gemini key can now be supplied via
  the plugin's `userConfig` (`sensitive: true`), so Claude Code stores it in the
  OS keychain instead of leaving it plaintext in the built `plugin.json`.
  Resolution order is `USER_CONFIG_GOOGLE_API_KEY` → `GOOGLE_API_KEY` env →
  `.academic-helper/secrets.json`. Strictly additive: every pre-existing path
  still resolves, including the lowercase `google_api_key` secrets-file field.
- **Resumable voice interview** — `.academic-helper/voice-checkpoint.json` is
  written after *every answered question*. `/voice` with no arguments resumes by
  default and reports position ("session 3 of 7, 12 of ~40 answered");
  `--restart` archives rather than deletes; `--session N` jumps.
- **`check-voice-populated.py`** — deterministic stub/populated check for
  `AUTHOR_VOICE.md` (exit 0 populated, 1 stub, 2 unreadable), with the rule
  documented in `skills/voice/references/stub-definition.md`.
- **`/write` voice precondition gate** — `/write` now refuses to draft against a
  stub voice file and directs the user to `/voice`. Fails closed on exit 2: an
  unreadable voice file is not treated as populated.
- **`disable-model-invocation: true`** on `init`, `setup`, and `voice` — the
  three skills that write persistent state, spend money, or hijack a session for
  ~70 minutes. They remain runnable by explicit `/name` invocation.

### Fixed

- **Voice distillation ran only after sessions 1 and 7.** This is the root cause
  of the long-standing "AUTHOR_VOICE.md is a stub" complaint: stopping partway
  through froze the session-1 output in place. The distiller now runs after every
  completed session, and partial profiles are stamped with an explicit coverage
  line instead of passing as complete.
- **8 npm vulnerabilities** (1 low, 4 moderate, 3 high) in the Gemini MCP
  server's dependencies → **0**. Six resolved by `npm audit fix`; the last two
  required `@google/genai` `^0.3.0` → `^1.26.0`, the smallest release that drops
  the vulnerable transitive `uuid`. No `--force` was used.
- **`build-plugins.sh` silently dropped manifest fields.** Its jq filter forwarded
  only `mcpServers`, so the new `userConfig` block would have vanished at build
  time; its awk extraction carried only `description`/`allowed-tools`, so
  `disable-model-invocation` would have been bypassable through the generated
  command copy. Both extended.
- **Literal plugin path** in `skills/write/SKILL.md` — the Hebrew punctuation
  validator was invoked as `plugins/academic-writer/scripts/...` instead of
  `${CLAUDE_PLUGIN_ROOT}/scripts/...`.

### Changed

- **Skills brought under the 500-line cap** via progressive disclosure:
  `init` 707 → 405, `write` 619 → 485, `voice` → 198. Detail moved verbatim into
  `references/*.md`; no step was dropped, only delegated.
- **Voice question bank trimmed** — two verbatim cross-session duplicates and one
  near-duplicate removed, two Hazal-transliteration questions merged. Session 3 is
  now declared the minimum-viable-voice milestone, so stopping there is a
  legitimate finish rather than an abandonment.
- The voice interviewer now **confirms** what the voice-miner inferred from
  `past-articles/` instead of asking cold.

### Notes

- `required-mcp-servers` was investigated and **does not exist** in current Claude
  Code. No such field was added anywhere. Every skill touching `mcp__gemini-api__*`
  has a documented Claude-only fallback, so it would not have applied regardless.
- The MCP `channels` pattern was likewise investigated and found to be for servers
  *pushing* messages into a session, not for supplying credentials. `userConfig` is
  the correct mechanism and is what shipped.
- Two pre-existing test failures remain in `test_voice_e2e_stage1.py` and
  `test_voice_migrate.py`, unrelated to this release and untouched by it.

## [0.5.1] and earlier

See git history.
