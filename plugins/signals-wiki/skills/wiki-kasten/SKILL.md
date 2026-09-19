---
name: wiki-kasten
description: File long-running wiki docs and chained scratch zettels.
version: 0.1.0
author: Ryan Hill (@rch), Weathership
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [wiki, zettel, current, scratch]
    category: note-taking
    related_skills: [zettel, llm-wiki]
---

# Wiki Kasten Skill

Keep the Hermes wiki as a Signals kasten: long-running documents under
`current/`, temporal zettels under `scratch/`, superseded pages under
`archive/`. AgentRTC and Hermes both follow this. Not a federated wiki.

## When to Use

- User asks to read, update, or create wiki notes, design docs, or drafts.
- A live AgentRTC discussion should leave a trail on a current document.
- User mentions prev/next, scratch zettels, or the wiki vault.

## Prerequisites

Vault is `$WIKI_PATH` or `${HERMES_HOME}/wiki`. Plugin `signals-wiki`
enabled. `zettel_capture` from `signals-zettel` is available.

## How to Run

Orient, then `read_file` / `write_file` / `zettel_capture`. Paths are
`wiki/current/...` and `wiki/scratch/YYYY-MM-DD/HHMMSS_slug.md`.

## Quick Reference

| Layer | Path | What belongs there |
|---|---|---|
| Current | `current/<section>/<slug>.md` | Long-running docs (design, article drafts) |
| Scratch | `scratch/YYYY-MM-DD/HHMMSS_slug.md` | One discussion beat, dated |
| Archive | `archive/...` | Superseded current docs |

Scratch frontmatter: `about`, `about_path`, `prev`, `next`.

## Procedure

1. `read_file` `wiki/SCHEMA.md` and `wiki/index.md` before creating pages.
2. New or updated **long-running** doc → `wiki/current/<section>/<slug>.md`
   with YAML frontmatter. Add it to `index.md`. Append `log.md`.
3. **Discussion of a current doc** (AgentRTC or Hermes) → `zettel_capture`
   with `body` (changelog or note + `[[wikilink]]` to the doc) and `about`
   set to that doc's path or slug. The tool sets `prev` to the last zettel
   about that doc and writes `next` on the previous file.
4. Do not put discussion crumbs in `current/`. Do not put the article itself
   only in `scratch/`.
5. Do not say a file is on disk unless `write_file` returned `verified` or
   `zettel_capture` returned `ok` with `path`. Then `read_file` that path.

## Pitfalls

- `wiki/` is the vault, not cwd. Use `wiki/current/...`, never a jail `wiki/`.
- `./wiki` is a project-local tree, not this vault.
- Empty `next:` on the newest zettel is correct.
- `archive/` may be empty.

## Verification

`read_file` the new path. For a chain, the previous zettel's `next:` equals
the new `relpath`, and the new file's `prev:` equals the previous `relpath`.
