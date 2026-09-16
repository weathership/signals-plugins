---
name: holoviews-viz
description: "Fade HoloViews stills onto the AgentRTC video feed."
version: 0.1.0
---

# HoloViews on AgentRTC

Render scientific figures **on the engine** and fade them over the looping
clip. The audience sees video, not a dashboard tab. Bishop/Ripley drive
the figure with tools — there is no Bokeh click path on the WebRTC peer.

## Tools

- `viz_show` — fade in. `kind=aperture` (Aegir SKOS chord) or `chord` /
  `scatter` / `curve` / `heatmap`. `source=aegir` when the federated
  workspace package is importable.
- `viz_select` — re-render the current still with a node highlighted.
- `viz_clear` — fade back to the looping clip.

Do not say the figure is on the feed until `viz_show` returned `"ok": true`.

## First pass

Plain HoloViews (matplotlib backend) when installed; matplotlib chord
fallback otherwise. No Dask, no Datashader.
