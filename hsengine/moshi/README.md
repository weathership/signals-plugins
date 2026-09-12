# agent-rtc: Kyutai STT for Hermes WebRTC captions

YK leaf: `root.internal.inference.agent-rtc` (dash is valid; see
`root.external.rate-metered`). **1 GPU guaranteed**, 1 application.

The devenv `moshi` process is a **supervisor** (control `:5081`) that is
resident with Hermes. On WebRTC Connect this engine **declares** a
coordination Activity (`interactive_session`) to Signals; the Activity's
claims ARE the YuniKorn configuration and **Signals applies them**. This
tree never calls `kubectl`. CUDA `moshi-server` (`:5080`) then starts on
the host and stops on the last Disconnect:

1. `Scheduler/DeclareActivity` with the local GPU claim
   `root.internal.inference.agent-rtc` GPU 1 (moshi / Kyutai STT).
   Cerebras thinking is `root.external.token-metered`: remote pay-per-token
   Qwen 3.8-27B, no local GPU and no YK GPU floor.
2. Signals materialises the Airflow run and asserts the agent-rtc claim.
3. Host moshi-server starts on the agent-rtc GPU: last free index after
   peer ``Engine/Status.gpu_ids`` (heavy packs from 0). Leases only refuse.
4. Hermes Complete for `agent`/`thinking` uses Cerebras `qwen-3.8-27b`.

Disconnect: stop moshi-server, `ReleaseActivity`. Peers restore their
desired sets from the release (or the horizon).

The Listen tab burns **user** speech onto the outbound video. That is
**Kyutai STT** (`stt-1b-en_fr`) served by **moshi-server** (Rust/Candle)
after the Activity is in force.

Outbound audio is one WebRTC track of **agent speech only** (clip
soundtrack omitted while dialog is iterated). On Connect, Cerebras
(`qwen-3.8-27b`) returns a short line that Kyutai TTS (`tts-1.6b-en_fr`)
reads aloud; user pauses then get a spoken reply.

There is no whisper/CPU path. If Signals refuses the declare, moshi-server
is missing, or no GPU can be leased, agent-rtc is unavailable.

Moshi 7B dialogue is a different module on this same stack: its text
stream is the assistant inner monologue, not a transcript of the mic.

Cargo `moshi-server` is a **Nix-linked** ELF (PT_INTERP = nix glibc).
devenv ships a wrap of the same name: isolated NVIDIA `.so` copies
(atelier) + `lib.makeLibraryPath` (openssl, opus, libstdc++). Never put
host `/lib` on that process's `LD_LIBRARY_PATH` — Ubuntu 2.35 libc wins
and dies on `GLIBC_2.39`. Inverse of Gaius `tinybox-ninja.sh` (host ELF
must not see Nix glibc).
