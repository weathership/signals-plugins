(function () {
  "use strict";

  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK || !window.__HERMES_PLUGINS__) return;

  const React = SDK.React;
  const { useState, useEffect, useRef } = SDK.hooks;
  const C = SDK.components;
  const API = "/api/plugins/signals-listen";
  const POSTER = "/dashboard-plugins/signals-listen/poster.jpg";

  function h(type, props) {
    const children = Array.prototype.slice.call(arguments, 2);
    return React.createElement.apply(React, [type, props].concat(children));
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

  function ListenPage() {
    const videoRef = useRef(null);
    const pcRef = useRef(null);
    const sessionRef = useRef(null);
    const micRef = useRef(null);
    const [status, setStatus] = useState(null);
    const [statusErr, setStatusErr] = useState("");
    const [conn, setConn] = useState("idle");
    const [detail, setDetail] = useState("");
    const [source, setSource] = useState("");
    const [sendMic, setSendMic] = useState(true);
    const [busy, setBusy] = useState(false);

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
      setDetail("");
      try {
        const pc = new RTCPeerConnection({
          iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
        });
        pcRef.current = pc;
        pc.addTransceiver("video", { direction: "recvonly" });
        if (sendMic) {
          try {
            const mic = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
            micRef.current = mic;
            mic.getAudioTracks().forEach(function (t) { pc.addTrack(t, mic); });
            setDetail("mic attached — captions burn into the video");
          } catch (micErr) {
            pc.addTransceiver("audio", { direction: "recvonly" });
            setDetail("mic unavailable (" + micErr + "); video-only");
          }
        } else {
          pc.addTransceiver("audio", { direction: "recvonly" });
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
          }),
        });
        await pc.setRemoteDescription({ sdp: answer.sdp, type: answer.type || "answer" });
        pc.getReceivers().forEach(function (r) { attachTrack(r.track); });
        sessionRef.current = answer.session_id || null;
        setSource(answer.source || "");
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
    }

    const webrtcReady = status && status.webrtc;
    const live = busy || conn === "connecting" || conn === "connected";
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
          h(CardTitle, null, "Listen"),
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
              h(Checkbox, {
                checked: sendMic,
                onCheckedChange: function (v) { setSendMic(!!v); },
                onChange: function (e) { setSendMic(!!(e.target && e.target.checked)); },
                type: "checkbox",
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
        ),
      ),
    );
  }

  window.__HERMES_PLUGINS__.register("signals-listen", ListenPage);
})();
