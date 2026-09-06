# Nautilus FSM DSL ↔ Hermes cron (bidirectional)

This is the **Signals–Hermes integration plugin**: one name in the
Nautilus instance, the same name in Hermes automations. Signals operators
see jobs in the **Hermes dashboard `/cron` UI**; a **local Nautilus**
beside this engine (`hsengine` `:50651`, supervisor on a loopback port
like Gaius `:50061`) verifies they actually fire.

Hermes devenv runs **engine + dashboard + Caddy + RustFS + Nautilus**
(`devenv up -d`). systemd: `hermes.service` (oneshot devenv up) plus
`hermes-nautilus-tick.timer`. Follow-only (`RESTART_STRATEGY_NONE`) until
promotion; not inside `run_agent.py`. Cron observation is
`SOURCE_KIND_HERMES_CRON` on `executions.db` / `jobs.json` — Nautilus
never scrapes the dashboard.

---

Gaius’s **canonical workflow serialization** is not `jobs.json` and not
`gaius.engine.fsm.FsmPosition`. It is the Nautilus **instance**:
`zndx.supervision.v1.Supervisor` textproto
(`config/supervision/<project>.textproto`).

- **Grammar** lives in signals-protocol (`supervision.proto` +
  `nautilus_supervision.md`). It never names Hermes, a script, or Imagine.
- **Instance** is the only place a project, a cron phrase, or a rubric
  appears. Gaius: `PROCESS_KIND_SCHEDULED_TASK` + `cadence.cron` mirroring
  pg_cron. Hermes already ships a follow-only tree
  (`config/supervision/hermes.textproto`) with engine/dashboard/gateway.

`FsmPosition` in Gaius is a **derived stamp** over existing timestamps
(QUEUED/CLAIMED/DONE_…, YK ADMIT_*). Do not treat that Python module as
the DSL.

## What to project

| Nautilus (canonical) | Hermes `~/.hermes/cron/jobs.json` (realized) |
|----------------------|-----------------------------------------------|
| `Process.id` | job `name` (stable); hex `id` is Hermes-runtime |
| `Cadence.cron` | `schedule` (5-field). Hermes `"every 15m"` → `attrs.schedule_phrase` until Cadence grows a phrase field |
| `Cadence.net_seconds` | inactivity bound hint (`HERMES_CRON_TIMEOUT` ≥ this) |
| `depends_on` | document only (Hermes cron has no DAG) |
| `Expectation` | Nautilus Backlog only — not a jobs.json field |
| `observation.locator` | job name for `SOURCE_KIND_HERMES_CRON` |

**Do not round-trip** Hermes runtime: `last_run_at`, `failure_streak`,
`run_claim`, execution ledger. Those stay in `jobs.json` /
`executions.db`. The DSL is *what should run*; JSON is *what ran*.

## Additive grammar (design)

Promote what Nautilus must **observe** to kinds; keep Hermes payload in
attrs until the supervisor needs it:

```
PROCESS_KIND_HERMES_CRON_JOB = 9;   // realized by hermes cron
SOURCE_KIND_HERMES_CRON = 9;        // jobs.json + executions.db
```

Optional nested payload (projector reads this; Nautilus may ignore):

```
message HermesCron {
  bool no_agent = 1;
  string script = 2;            // profile-relative or absolute
  string prompt = 3;            // unused when no_agent
  string deliver = 4;           // "local" | "origin" | ...
  bool oauth_only_imagine = 5;  // DENY XAI_API_KEY on this job
  string schedule_phrase = 6;   // "every 15m" when not 5-field
}
```

Until that message lands, the same keys ride `Process.attrs` (opaque to
Nautilus, read by the projector). That matches the protocol rule:
interpret in kinds; everything else in attrs.

## Bidirectional sync

**DSL → JSON (authoritative for desired state):**

1. `nautilus validate config/supervision/hermes.textproto`
2. Projector upserts jobs whose `name == Process.id` (create/edit
   schedule, script, no_agent, deliver). Does not delete jobs that are
   not in the instance unless `--prune`.
3. Idempotent; Hermes hex ids preserved on match-by-name.

**JSON → DSL (Hermes inputs):**

1. Dashboard / `hermes cron edit` is a valid author.
2. Projector writes `cadence.cron` / `HermesCron` / attrs back onto the
   matching `Process`. New jobs without a Process.id get a new
   `processes { }` block (kind HERMES_CRON_JOB, parent `gateway`).
3. `spec_version` bumps on DSL write so Nautilus reloads the tree.
4. Conflict: if both sides changed, **DSL wins on next forward sync**
   unless the JSON edit is newer than `spec_version` timestamp — record
   `attrs { key: "hermes_mtime" }` on reverse sync.

Plugin-only: `signals-cron-sync` (CLI + projector) lives in this repo
with the other Signals Hermes plugins. Dashboard `/cron` is already
core Hermes — we do not replace it; we **fill** it from the instance.
No `run_agent.py` patches.

## Imagine prototype as an instance row

```
processes {
  id: "cron.imagine_keyframe"
  kind: PROCESS_KIND_HERMES_CRON_JOB   # or SCHEDULED_TASK + attrs until enum lands
  parent: "gateway"
  restart: RESTART_STRATEGY_NONE
  observation { source: SOURCE_KIND_HERMES_CRON locator: "cron.imagine_keyframe" }
  cadence { cron: "*/15 * * * *" net_seconds: 600 }
  depends_on: "engine"
  attrs { key: "no_agent" value: "true" }
  attrs { key: "oauth_only_imagine" value: "true" }
  attrs { key: "deliver" value: "local" }
  expectation {
    category: EXPECTATION_CATEGORY_TICK
    horizon_slot: 3
    channel: CHANNEL_AGENDA_EVENT
    rationale: "15 min Imagine clip; miss = no latest.mp4 this hour"
  }
}
```

Nautilus scores the job; Hermes cron fires it; the dashboard lists it.
Gaius is not in this tree except as `Engine/Render` `via` the engine
process. Verification: Backlog cell for `cron.imagine_keyframe` goes
`Ok` when `executions.db` shows a completed run inside the admission
window — the same id Signals users see under Automations.

## Not this

- Putting `jobs.json` in git as the SoR
- Teaching Nautilus to parse Hermes JSON
- Gaius `FsmPosition` as the workflow file
- Bidirectional sync of run history into textproto
