---
name: holoviews-viz
description: "Live HoloViews/Bokeh on the AgentRTC video track via CDP screencast."
version: 0.1.0
---

# HoloViews on AgentRTC

This is a **Signals plugin**. The engine serves a standalone Bokeh/HoloViews
document, one **headless Chromium** (`--headless=new`) per Connect, CDP
`Page.startScreencast` as the live WebRTC program track. Listen is the
audience. Aegir is optional data (aperture chord), not a deploy requirement.

Humans join a meeting already in progress among named agents. They ask
questions; they do not drive the plot. Agents use `viz_input` (CDP mouse)
and `viz_select`.

## Tools

- `viz_show` — fade the live compositor in (`kind=chord|aperture|scatter|curve|heatmap`).
- `viz_select` — retarget the document (highlight a node).
- `viz_input` — agent pointer in CSS pixels of the 1280×720 viewport.
- `viz_clear` — fade back to the looping clip (screencast stops).

Do not say the figure is on the feed until `viz_show` returned `"ok": true`.
`getDisplayMedia` is a later spectator-share ingest, not how HoloViews is captured.
