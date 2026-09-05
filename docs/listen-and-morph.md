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
| `plugins/signals-listen` | dashboard UI + `plugin_api.py` | Mic, morph canvas, plugin HTTP/WS |
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
| Gaius keyframe | Plugin tool or `plugin_api` POST: graph snapshot → Gaius viz (HTTP or object store). **Not** `zndx.engine.v1` |
| Live picture | Plugin canvas: last still + WebGL morph; blend when `GET /api/plugins/signals-listen/keyframe` returns a new URL |
| Voice turn → agent | `plugin_api` runs a one-shot `AIAgent.chat()` / `hermes -q` in the dashboard process (plugins may import Hermes). Result shown on the plugin page. Does **not** type into Chat PTY. |
| Auth | Plugin routes sit behind the dashboard gate (already) |

## Data flow

```
laptop mic  --getUserMedia-->  plugin JS
                 |                    |
                 | blob/pcm           | still URL + κ graph
                 v                    v
         POST /api/audio/transcribe   GET /api/plugins/signals-listen/keyframe
                 |                    ^
                 v                    |
         plugin_api: agent turn       Gaius LuxCore (evicted GPU)
                 |                    |
                 +--> signals-graph state --snapshot--> Gaius
                 +--> morph canvas (P-frames in the browser)
```

Cadence:

- **Audio:** utterance blobs first (desktop pattern, uses existing transcribe). Streaming PCM/WS on `plugin_api` WebSocket only if FastAPI plugin routers accept `@router.websocket` (verify at implement; if not, blobs are enough for VAD PTT).
- **Graph:** append on each `post_llm_call` (role, tokens hash, tool names). κ can be a cheap local stub until Gaius returns curvature with the still.
- **Keyframe:** after N turns or a topic shift, plugin_api hands the graph to Gaius; poll/push a PNG/WebP URL (RustFS `hermes-artifacts` is fine). Interpolator never calls pyluxcore.
- **Morph:** two textures + mix; Procrustes/layout lock is Gaius’s job on the still (stable camera). Hermes only crossfades.

## Gaius contract (out of this repo)

Hermes does not vendor LuxCore. Gaius exposes **something fetchable**:

- HTTP on the Gaius gateway (engine-local, not signals-protocol), or
- object written to a known bucket/key.

Input: graph JSON (nodes, edges, optional embedding refs). Output: image
URL + optional `kappa` overlay metadata. Render stays PATHOCL on an
evicted GPU, same as cards.

## WebRTC (explicitly later)

Same plugin, new transport: `RTCPeerConnection` in the JS bundle, signaling
JSON on `plugin_api`. Audio track = laptop; video track = interpolator
canvas `captureStream()`. Still not `zndx.engine.v1`. ICE/TURN only when
this ships.

## Out of scope (would be upstream)

- Injecting transcripts into the Chat PTY
- Teaching `web/` getUserMedia
- `tui_gateway` `voice.record` using browser audio
- signals-protocol media RPCs

## Implement order (when we leave design)

1. Dashboard plugin tab: mic → `/api/audio/transcribe` → show text; morph
   canvas with a placeholder still.
2. `signals-graph` hooks writing `ctx.state`.
3. Keyframe fetch from Gaius + crossfade.
4. Plugin-local agent turn so listen is a conversation, not a notepad.
5. WebRTC mux when barge-in needs it.
