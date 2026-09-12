---
name: zettel
description: File a clipboard zettel into the Hermes wiki vault.
version: 0.1.0
author: Ryan Hill (@rch), Weathership
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [zettel, wiki, clipboard, notes]
    category: note-taking
---

# Zettel Skill

Capture a scratch zettel under the Hermes wiki vault in one step: Gaius-style
filename plus clipboard (or pasted) body. Does not use the bundled `obsidian`
skill or `/paste` (images only).

## When to Use

- User runs `/zettel` or asks to file clipboard / pasted notes into the wiki.
- User wants a scratch zettel without walking Obsidian or llm-wiki ingest.

## Prerequisites

Plugin `signals-zettel` enabled. Vault is `OBSIDIAN_VAULT_PATH` or `WIKI_PATH`
or `${HERMES_HOME}/wiki`.

## How to Run

Prefer the slash command (reads the host clipboard in this process):

```
/zettel optional title
```

From the agent, call `zettel_capture`. Omit `body` to read the clipboard.
If the user already pasted the note in the chat, pass that text as `body`.

## Quick Reference

| Field | Value |
|-------|--------|
| Path | `scratch/YYYY-MM-DD/HHMMSS_slug.md` under the vault |
| Resource | `wiki:scratch/...` |
| Tool | `zettel_capture` |

## Procedure

1. If the user invoked `/zettel`, the plugin already wrote the file — report
   the returned `relpath` and `resource`. Do not rewrite it.
2. Otherwise call `zettel_capture` with `title` when they named the note.
3. On `ok: false` and empty clipboard, ask them to copy the text and run
   `/zettel` again. Do not probe the OS clipboard with `terminal`.
4. Leave Gaius lattice KB alone; this vault is Hermes-local.

## Pitfalls

- `/paste` is clipboard **images**. It will not fill a zettel.
- Jail/SSH sessions often have no host clipboard — `/zettel` then fails;
  the user should paste the body into chat and you pass `body`.

## Verification

The tool/slash result includes `ok`, `relpath`, `resource`, and `bytes`.
`read_file` on the absolute `path` should show the captured markdown.
