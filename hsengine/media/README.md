# Engine-local media fixtures

`gaius-card.jpg` — published Gaius LuxCore still used as the Imagine I-frame
and as the dashboard poster before a WebRTC session connects.

The looping WebRTC demo clip lives on Hermes RustFS
(`s3://hermes-artifacts/webrtc/demo.mp4` /
`/raid/build/hermes/data/hermes-artifacts/webrtc/demo.mp4`)
and is not committed (16s H.264, ~7 MiB). A copy may also sit at
`fixtures/demo.mp4` (gitignored).

Override with `HERMES_WEBRTC_VIDEO` (captured in `config/base.conf`).
Signaling is `hermes.engine.HermesEngine/WebRtcOffer`, not `zndx.engine.v1`.
Inbound mic audio is streamed to Kyutai STT (moshi-server / Candle) on
YK leaf `root.internal.inference.agent-rtc` (1 GPU guaranteed) and burned
into the outbound video. No whisper/CPU path.
