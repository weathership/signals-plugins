(function () {
  "use strict";

  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK || !window.__HERMES_PLUGINS__) return;

  const React = SDK.React;
  const { useState, useEffect, useRef } = SDK.hooks;
  const C = SDK.components;
  const API = "/api/plugins/signals-listen";
  const POSTER = "/dashboard-plugins/signals-listen/poster.jpg";
  const JS_VERSION = "listen-js-20260916a";

  function h(type, props) {
    const children = Array.prototype.slice.call(arguments, 2);
    return React.createElement.apply(React, [type, props].concat(children));
  }

  function stashAgenda() {
    try {
      var u = new URL(window.location.href);
      var a = u.searchParams.get("agenda") || "";
      if (!a && u.hash) {
        var hm = u.hash.match(/agenda=([^&]+)/);
        if (hm) a = decodeURIComponent(hm[1].replace(/\+/g, " "));
      }
      if (a) sessionStorage.setItem("agent-rtc-agenda", a);
    } catch (_e) {}
  }
  stashAgenda();
  function listenerTimezone() {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
    } catch (_e) {
      return "";
    }
  }
  function agendaId() {
    try {
      var u = new URL(window.location.href);
      var a = u.searchParams.get("agenda") || "";
      if (!a && u.hash) {
        var hm = u.hash.match(/agenda=([^&]+)/);
        if (hm) a = decodeURIComponent(hm[1].replace(/\+/g, " "));
      }
      if (a) {
        sessionStorage.setItem("agent-rtc-agenda", a);
        return a;
      }
      return sessionStorage.getItem("agent-rtc-agenda") || "";
    } catch (_e) {
      return "";
    }
  }

  function waitIce(pc, ms) {
    if (pc.iceGatheringState === "complete") return Promise.resolve();
    return new Promise(function (resolve) {
      const t = setTimeout(resolve, ms);
      pc.addEventListener("icegatheringstatechange", function onChange() {
        if (pc.iceGatheringState === "complete") {
          pc.removeEventListener("icegatheringstatechange", onChange);
          clearTimeout(t);
          resolve();
        }
      });
    });
  }

  (function bounceHttpListen() {
    var dest = window.__HERMES_LISTEN_URL__;
    if (!dest || window.isSecureContext) return;
    try {
      var u = new URL(dest);
      u.search = window.location.search;
      u.hash = window.location.hash;
      window.location.replace(u.toString());
    } catch (_e) {}
  })();

  function ListenPage() {
    const videoRef = useRef(null);
    const pcRef = useRef(null);
    const sessionRef = useRef(null);
    const micRef = useRef(null);
    const audioCtxRef = useRef(null);
    const [status, setStatus] = useState(null);
    const [statusErr, setStatusErr] = useState("");
    const [conn, setConn] = useState("idle");
    const [detail, setDetail] = useState("");
    const [source, setSource] = useState("");
    const [sendMic, setSendMic] = useState(true);
    const [busy, setBusy] = useState(false);
    const [draft, setDraft] = useState("");
    const [sending, setSending] = useState(false);
    const [stopping, setStopping] = useState(false);
    const [lines, setLines] = useState([]);
    const [sessionId, setSessionId] = useState("");

    useEffect(function () {
      let cancelled = false;
      SDK.fetchJSON(API + "/status")
        .then(function (data) {
          if (!cancelled) {
            setStatus(data);
            setStatusErr("");
          }
        })
        .catch(function (err) {
          if (!cancelled) setStatusErr(String(err && err.message ? err.message : err));
        });
      return function () {
        cancelled = true;
        hangupLocal();
      };
    }, []);

    async function connect() {
      if (busy || pcRef.current) return;
      setBusy(true);
      setConn("connecting");
      setDetail(JS_VERSION);
      try {
        // Mic first, on the Connect click, with unconstrained audio. Chrome
        // will not prompt if the origin is already Allowed; extra constraints
        // (channelCount) fail OverconstrainedError with no prompt.
        let mic = null;
        if (sendMic) {
          try {
            if (!window.isSecureContext) {
              throw new Error("page is not HTTPS — Chrome will not open the mic");
            }
            mic = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
          } catch (micErr) {
            const name = (micErr && micErr.name) || "Error";
            const msg = (micErr && micErr.message) || String(micErr);
            hangupLocal();
            setConn("idle");
            setDetail("mic " + name + ": " + msg + " (origin " + location.origin + ")");
            setBusy(false);
            return;
          }
        }
        const AC = window.AudioContext || window.webkitAudioContext;
        if (AC) {
          audioCtxRef.current = new AC();
          if (audioCtxRef.current.resume) audioCtxRef.current.resume();
        }
        const pc = new RTCPeerConnection({
          iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
        });
        pcRef.current = pc;
        pc.addTransceiver("video", { direction: "recvonly" });
        if (mic) {
          micRef.current = mic;
          const tracks = mic.getAudioTracks();
          if (!tracks.length) throw new Error("no audio tracks");
          tracks.forEach(function (t) {
            t.enabled = true;
            if (t.muted) {
              try { t.enabled = true; } catch (_e) {}
            }
            pc.addTrack(t, mic);
          });
          const label = tracks[0].label || "default";
          const live = tracks[0].readyState;
          setDetail(JS_VERSION + " · mic " + live + " · " + label);
        } else {
          pc.addTransceiver("audio", { direction: "recvonly" });
          setDetail(JS_VERSION + " · mic off — type below to reply");
        }
        function attachTrack(track) {
          const el = videoRef.current;
          if (!el || !track) return;
          let ms = el.srcObject;
          if (!(ms instanceof MediaStream)) {
            ms = new MediaStream();
            el.srcObject = ms;
          }
          if (!ms.getTracks().some(function (t) { return t.id === track.id; })) {
            ms.addTrack(track);
          }
          el.muted = false;
          el.defaultMuted = false;
          el.volume = 1;
          const p = el.play();
          if (p && p.catch) p.catch(function () {});
          if (track.kind === "audio" && audioCtxRef.current) {
            try {
              const ctx = audioCtxRef.current;
              if (ctx.state === "suspended" && ctx.resume) ctx.resume();
              const src = ctx.createMediaStreamSource(new MediaStream([track]));
              src.connect(ctx.destination);
              setDetail(JS_VERSION + " · audio track + AudioContext");
            } catch (e) {
              setDetail(JS_VERSION + " · audio track (ctx " + e + ")");
            }
          }
        }
        pc.ontrack = function (ev) {
          attachTrack(ev.track);
        };
        pc.onconnectionstatechange = function () {
          setConn(pc.connectionState || "unknown");
        };
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        await waitIce(pc, 4000);
        const answer = await SDK.fetchJSON(API + "/offer", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            sdp: pc.localDescription.sdp,
            type: pc.localDescription.type,
            agenda: agendaId(),
            timezone: listenerTimezone(),
          }),
        });
        await pc.setRemoteDescription({ sdp: answer.sdp, type: answer.type || "answer" });
        pc.getReceivers().forEach(function (r) { attachTrack(r.track); });
        sessionRef.current = answer.session_id || null;
        setSessionId(answer.session_id || "");
        setSource(answer.source || "");
        setLines([]);
        setConn(pc.connectionState === "connected" ? "connected" : "connecting");
        SDK.fetchJSON(API + "/status")
          .then(function (data) { setStatus(data); })
          .catch(function () {});
      } catch (err) {
        setConn("failed");
        setDetail(String(err && err.message ? err.message : err));
        hangupLocal();
      } finally {
        setBusy(false);
      }
    }

    function hangupLocal() {
      const sid = sessionRef.current;
      sessionRef.current = null;
      if (micRef.current) {
        micRef.current.getTracks().forEach(function (t) { t.stop(); });
        micRef.current = null;
      }
      if (pcRef.current) {
        try { pcRef.current.close(); } catch (_e) {}
        pcRef.current = null;
      }
      if (videoRef.current) videoRef.current.srcObject = null;
      if (sid) {
        SDK.fetchJSON(API + "/hangup", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sid }),
        }).catch(function () {});
      }
    }

    function disconnect() {
      hangupLocal();
      setConn("idle");
      setSource("");
      setDraft("");
      setSessionId("");
    }

    async function sendText() {
      const sid = sessionRef.current;
      const text = (draft || "").trim();
      if (!sid || !text || sending) return;
      setSending(true);
      try {
        await SDK.fetchJSON(API + "/say", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sid, text: text }),
        });
        setLines(function (prev) {
          return prev.concat([{ role: "you", text: text }]);
        });
        setDraft("");
      } catch (err) {
        setDetail("say: " + String(err && err.message ? err.message : err));
      } finally {
        setSending(false);
      }
    }

    async function stopSpeaking() {
      const sid = sessionRef.current;
      if (!sid || stopping) return;
      setStopping(true);
      try {
        const r = await SDK.fetchJSON(API + "/stop", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sid }),
        });
        const dropped = (r && r.dropped_samples) || 0;
        setDetail(JS_VERSION + " · stopped (" + dropped + " samples dropped)");
        setLines(function (prev) {
          return prev.concat([{ role: "system", text: "stopped speaking" }]);
        });
      } catch (err) {
        setDetail("stop: " + String(err && err.message ? err.message : err));
      } finally {
        setStopping(false);
      }
    }

    function onDraftKey(e) {
      if (!e) return;
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendText();
      }
    }

    const webrtcReady = status && status.webrtc;
    const live = busy || conn === "connecting" || conn === "connected";
    const onCall = !!sessionId;
    const Card = C.Card || "div";
    const CardHeader = C.CardHeader || "div";
    const CardTitle = C.CardTitle || "h2";
    const CardContent = C.CardContent || "div";
    const Button = C.Button || "button";
    const Badge = C.Badge || "span";
    const Checkbox = C.Checkbox || "input";

    return h("div", { className: "signals-listen space-y-4" },
      h(Card, null,
        h(CardHeader, null,
          h(CardTitle, null, agendaId() ? "Listen · session" : "Listen"),
          h("p", { className: "text-sm text-muted-foreground" }, JS_VERSION + (agendaId() ? " · " + agendaId() : "")),
        ),
        h(CardContent, null,
          h("div", { className: "signals-listen-row" },
            h(Badge, null, conn),
            status ? h(Badge, null, status.webrtc ? "engine webrtc" : "engine up, no webrtc") : null,
            status && status.stt ? h(Badge, null, "captions") : null,
            statusErr ? h("span", { className: "signals-listen-status" }, statusErr) : null,
          ),
          h("div", { className: "signals-listen-row" },
            h("label", { className: "text-sm", style: { display: "flex", gap: "0.4rem", alignItems: "center" } },
              h("input", {
                type: "checkbox",
                checked: sendMic,
                onChange: function (e) { setSendMic(!!(e.target && e.target.checked)); },
              }),
              "send mic for captions (Kyutai STT)",
            ),
          ),
          h("div", { className: "signals-listen-row" },
            h(Button, {
              onClick: connect,
              disabled: live || !webrtcReady,
            }, busy ? "Negotiating…" : (live ? "Connected" : "Connect")),
            h(Button, { onClick: disconnect, disabled: !live && conn === "idle" }, "Disconnect"),
          ),
          h("p", { className: "signals-listen-status" }, detail),
          h("video", {
            ref: videoRef,
            autoPlay: true,
            playsInline: true,
            controls: true,
            poster: POSTER,
          }),
          source ? h("p", { className: "signals-listen-source" }, "source " + source) : null,
          h("div", { className: "signals-listen-composer" },
            lines.length ? h("ul", { className: "signals-listen-log", "aria-live": "polite" },
              lines.slice(-8).map(function (line, i) {
                return h("li", { key: i, className: "signals-listen-log-" + line.role },
                  line.role === "you" ? "You: " : "",
                  line.text
                );
              })
            ) : null,
            h("textarea", {
              className: "signals-listen-input",
              rows: 2,
              value: draft,
              placeholder: onCall ? "Type a message to the agent" : "Connect first, then type here",
              disabled: !onCall || sending,
              onChange: function (e) { setDraft(e.target.value); },
              onKeyDown: onDraftKey,
              "aria-label": "Message to the agent",
            }),
            h("div", { className: "signals-listen-row" },
              h(Button, {
                onClick: sendText,
                disabled: !onCall || sending || !(draft || "").trim(),
              }, sending ? "Sending…" : "Send"),
              h(Button, {
                onClick: stopSpeaking,
                disabled: !onCall || stopping,
                variant: "destructive",
              }, stopping ? "Stopping…" : "Stop"),
            ),
            h("p", { className: "signals-listen-status" },
              "Enter sends · Shift+Enter for a new line · Stop cuts the agent mid-sentence"
            ),
          ),
        ),
      ),
    );
  }

  window.__HERMES_PLUGINS__.register("signals-listen", ListenPage);
})();
