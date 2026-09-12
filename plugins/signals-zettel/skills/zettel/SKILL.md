---
name: zettel
description: File pasted text as a scratch zettel in the wiki vault.
version: 0.1.1
author: Ryan Hill (@rch), Weathership
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [zettel, wiki, notes]
    category: note-taking
---

# Zettel Skill

Capture a scratch zettel under the Hermes wiki vault in one step. The
filename is Gaius-style; the body is the pasted argument. Does not use
the bundled `obsidian` skill, `/paste`, or the OS clipboard.

## When to Use

- User runs `/zettel` with the note text after the command.
- User asks to file pasted notes into the wiki vault.

## Prerequisites

Plugin `signals-zettel` enabled. Vault is `OBSIDIAN_VAULT_PATH` or `WIKI_PATH`
or `${HERMES_HOME}/wiki`.

## How to Run

```
/zettel <pasted text>
```

The slug is the first line (heading if present). From the agent, call
`zettel_capture` with `body` set to that same text.

## Quick Reference

| Field | Value |
|-------|--------|
| Path | `scratch/YYYY-MM-DD/HHMMSS_slug.md` under the vault |
| Resource | `wiki:scratch/...` |
| Tool | `zettel_capture` |

## Procedure

1. If the user invoked `/zettel` with a body, the plugin already wrote the
   file — report `relpath` and `resource`. Do not rewrite it.
2. Otherwise call `zettel_capture` with `body` equal to the pasted markdown.
3. On empty body, tell them the usage is `/zettel <pasted text>`.
4. Leave Gaius lattice KB alone; this vault is Hermes-local.

## Pitfalls

- `/paste` is clipboard **images**. It will not fill a zettel.
- Do not probe the OS clipboard with `terminal`.

## Verification

The tool/slash result includes `ok`, `relpath`, `resource`, and `bytes`.
`read_file` on the absolute `path` should show the captured markdown.
