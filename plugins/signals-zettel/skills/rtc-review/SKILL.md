---
name: rtc-review
description: Grok-review the last AgentRTC session into a scratch zettel for the next Connect.
version: 0.1.0
author: Ryan Hill (@rch), Weathership
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [zettel, wiki, grok, agent-rtc]
    category: note-taking
---

# AgentRTC Grok review

When the operator wants a frontier-model lift on the last AgentRTC call,
do not improvise a note. Run the slash (or the tool). Spoken Ripley stays
on Cerebras; this is a manual Chat-side consult.

## When to Use

- User runs `/rtc-review` or `/grok-review`.
- User asks Grok in Chat to review the last AgentRTC / Ripley session
  and leave a note for the next Connect.

## How to Run

```
/rtc-review
/rtc-review the kasten vs archive loop
/rtc-review --about current/design/canonical-state-schema.md
/rtc-review --session agent-rtc-<id>
```

From the agent, call `rtc_review` (optional `focus`, `about`, `session_id`).
Do not `zettel_capture` a paraphrase of the transcript yourself.

## Pickup

The file is `wiki/scratch/YYYY-MM-DD/HHMMSS_slug.md`. Next Connect within
about 12 minutes treats it as USER-PROVIDED opening entropy. Do not claim
Ripley has already seen it.

## Pitfalls

- Empty result means there is no `source=agent-rtc` session yet — Connect first.
- This is not `grok_consult` on the live call. Ripley does not speak the zettel
  until the next invent/Connect pass.
