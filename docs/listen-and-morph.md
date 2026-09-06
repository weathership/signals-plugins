# Hermes-side listen + morph — plugins only

LuxCore stays on **Gaius**. WebRTC stays **engine-local, later**. This pass
uses only documented Hermes plugin seams (no `run_agent.py` / `web/` /
`tui_gateway` patches). Install from this repo like the other Signals
plugins.

## Constraint

If it cannot be a `plugin.yaml` + `register(ctx)` Python plugin, a
dashboard `manifest.json` + JS bundle + `plugin_api.py`, or config-driven
STT/TTS, it is out of scope here.

**Cut we accept:** voice+viz live on a **plugin tab**, not inside the
embedded TUI PTY. There is no plugin API that writes keystrokes into
`/api/pty`. Forcing that would be the one upstream change; we do not
take it.

## Packages (this repo)

| Dir | Hermes kind | Job |
|-----|-------------|-----|
| `plugins/signals-listen` | dashboard UI + `plugin_api.py` | Mic, **viewer** of hsengine forward-sim, plugin HTTP/WS |
| `plugins/signals-graph` | general plugin (`post_llm_call`, `post_tool_call`) | Conversation graph JSON (points, edges, κ stubs) |
| existing `signals-oip` / `signals-memory` | already shipped | Lattice model + turn memory for the graph |

Optional later: `signals-webrtc` as a **second** dashboard/engine bundle
once duplex exists. Not this pass.

## Seams (all exist today)

| Need | Seam |
|------|------|
| HTTPS for `getUserMedia` | devenv Caddy `:9120` (already) |
| Mic in the browser | Dashboard plugin JS (Synth `micCapture` / desktop `use-mic-recorder`) |
| STT | `POST /api/audio/transcribe` and/or `GET /api/audio/voice-config` (client-direct, same as desktop) — **core routes, plugin is the client** |
| TTS | `POST /api/audio/speak` / speak-stream WS — same |
| Graph updates | `post_llm_call` / `post_tool_call` → `ctx.state` JSON |
| Gaius keyframe | `plugin_api` is a gRPC client of `zndx.engine.v1.Engine/Render` (see signals-protocol `keyframe.md`). Still bytes live on RustFS (`data_uri`); optional `preview_jpeg` on the RPC. |
| Live picture | **hsengine** forward-sim. Default: YK **one 4090 LIGHT** (accept quality vs Imagine). Enthusiastic: Grok **premium/Heavy subscription** Imagine i2v (`xai-oauth` only). **DENY** `XAI_API_KEY` / token-metered Imagine for this feature. Plugin is a viewer. Gaius = LuxCore only. |
| Voice turn → agent | `plugin_api` runs a one-shot `AIAgent.chat()` / `hermes -q` in the dashboard process (plugins may import Hermes). Result shown on the plugin page. Does **not** type into Chat PTY. |
| Auth | Plugin routes sit behind the dashboard gate (already) |

## Data flow

```
laptop mic  --getUserMedia-->  plugin JS
                 |                    |
                 | blob/pcm           | still URL + κ graph
                 v                    v
         POST /api/audio/transcribe   Engine/Render (gRPC → Gaius :50051)
                 |                    ^
                 v                    |
         plugin_api: agent turn       LuxCore still → RustFS data_uri
                 |                    |  (+ preview_jpeg on the RPC)
                 +--> signals-graph --graph_json--+
                 +--> hsengine LIGHT 4090 (YK) forward-sim → local RustFS → plugin viewer
```

Cadence:

- **Audio:** utterance blobs first (desktop pattern, uses existing transcribe). Streaming PCM/WS on `plugin_api` WebSocket only if FastAPI plugin routers accept `@router.websocket` (verify at implement; if not, blobs are enough for VAD PTT).
- **Graph:** append on each `post_llm_call` (role, tokens hash, tool names). κ can be a cheap local stub until Gaius returns curvature with the still.
- **Keyframe:** after N turns or a topic shift, `plugin_api` calls
  `Engine/Render` on Gaius with `graph_json`. Response `data_uri` is the
  SoR still on Signals RustFS. **hsengine** streams that object, replicas
  it on Hermes RustFS, and runs forward-sim as a **LIGHT** workload
  (one 4090; YuniKorn admits). A new `tx_id` blends in **in hsengine**.
  Gaius never interpolates. Browser never interpolates. No pyluxcore
  in this checkout.
- **Imagine i2v (subscription only):** if `providers.xai-oauth` (Grok
  premium / Heavy) has a live access token, send the I-frame to
  `grok-imagine-video-1.5` and **enthusiastically** use the clip. If the
  only credential is `XAI_API_KEY` (token-metered), **do not call Imagine**
  — fall through to local LIGHT interpolator. Never `prefer_api_key` on
  this path. Prompt: camera-only motion. Do not put Imagine on
  `zndx.engine.v1`.
- **Local i2v (always acceptable):** YK LIGHT 4090 interpolator. Quality
  delta vs Imagine is accepted so we never pay API token rates.
- **Layout lock** on the still is Gaius (stable camera / Procrustes).
  Hermes interpolates pixels, not Ricci.

## Protocol contract (`Engine/Render`)

See `specification/protocol/keyframe.md`. Hermes does not vendor LuxCore.
Gaius implements `Render`; other engines `UNIMPLEMENTED`. Product id
`gaius.viz.keyframes`; `kappa_json` rides the response so Hermes does not
recompute Ricci.

## WebRTC (explicitly later)

Same plugin, new transport: `RTCPeerConnection` in the JS bundle, signaling
JSON on `plugin_api`. Audio track = laptop; video track = **hsengine
forward-sim** (not a browser canvas). Still not `zndx.engine.v1`.
ICE/TURN only when this ships.

## Out of scope (would be upstream)

- Injecting transcripts into the Chat PTY
- Teaching `web/` getUserMedia
- `tui_gateway` `voice.record` using browser audio
- Duplex WebRTC on `zndx.engine.v1` (Render is stills only)

## Prototype via Hermes automations (cron)

Imagine i2v is **60–240s**. A live hsengine loop is the wrong first cut.
Hermes **cron** (dashboard `/cron`, `hermes cron`, `cronjob` tool) is the
automation surface.

**Shape:** `no_agent=True` + `script` (stdout is the job; **zero LLM**).
Do not use an agent turn for the prototype — no model pin, no toolset
widening, no paid-provider drift. The script:

1. Read graph JSON from plugin state / a well-known file under
   `get_hermes_home()` (cron uses `skip_memory=True`; do not rely on
   memory.prefetch).
2. Optionally `Engine/Render` on Gaius; if `UNIMPLEMENTED`, reuse the last
   still or a fixture image (prototype).
3. **If** `xai-oauth` has a live access token → `grok-imagine-video-1.5`
   image-to-video (camera-only prompt). **If** only `XAI_API_KEY` → skip
   Imagine, log `DENY token-metered`, exit 0 (or run a cheap local ffmpeg
   Ken-Burns on the still).
4. Write `latest.mp4` (and `tx_id`) to Hermes RustFS / profile dir.
5. Print a one-line receipt (URI, duration, auth=`xai-oauth`).

**Schedule:** `every 15m` or slower while iterating; `hermes cron run
<name>` for on-demand. Gateway must be ticking (`hermes gateway` / dashboard
cron). devenv today is engine+dashboard+caddy+rustfs — **add a gateway
process or run jobs by hand**.

**Timeouts:** cron inactivity watchdog defaults to **600s**
(`HERMES_CRON_TIMEOUT`; 0 = unlimited). Imagine’s 60–240s fits if the HTTP
client is not silent for 10 minutes. Heartbeat or raise the timeout; do not
assume the old “3 minute hard interrupt” still applies as wall-clock (it is
inactivity). One-shot `run_claim` TTL is separate (up to 1800s).

**Why not an agent cron with `video_generate`:** extra inference, must
allowlist `video` toolset, model-pin policy, 3-minute *agent loop* risk.
`no_agent` script imports the same xAI video plugin Python the tool uses.

**Viewer:** plugin tab polls `GET /api/plugins/signals-listen/latest` and
plays the last clip on a loop until the next receipt. That is the morph
stand-in until LIGHT interpolator exists.

**Delivery:** `deliver: local` (file under `cron/output/`); `[SILENT]` if
we do not want chat noise. Do not `bot-chat` every 15m.

## Implement order (when we leave design)

1. `no_agent` cron script: still (fixture or Render) → Imagine i2v if
   OAuth else skip → write `latest.mp4`; plugin tab loops it.
2. `signals-graph` hooks writing `ctx.state` for the script to read.
3. Wire `Engine/Render` when Gaius implements it.
4. Replace Ken-Burns/Imagine-loop with hsengine LIGHT interpolator when YK
   admits a 4090.
5. Plugin-local agent turn; WebRTC mux last.
