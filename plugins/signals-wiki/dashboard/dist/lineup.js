(function () {
  "use strict";

  // Lineup panels after Ægir (Ward Cunningham's original lineup). This is
  // not a federated wiki: no fork, no remote journal, no neighborhood.
  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK || !window.__HERMES_PLUGINS__) return;

  const React = SDK.React;
  const { useState, useEffect, useRef, useCallback } = SDK.hooks;
  const API = "/api/plugins/signals-wiki";
  const TRAIL_KEY = "hermes-wiki:lineup";

  function h(type, props) {
    const children = Array.prototype.slice.call(arguments, 2);
    return React.createElement.apply(React, [type, props].concat(children));
  }

  function loadTrail() {
    try {
      const raw = sessionStorage.getItem(TRAIL_KEY);
      const a = raw ? JSON.parse(raw) : null;
      if (Array.isArray(a) && a.length) return a;
    } catch (_e) {}
    return null;
  }

  function saveTrail(trail) {
    try {
      if (trail.length) sessionStorage.setItem(TRAIL_KEY, JSON.stringify(trail));
    } catch (_e) {}
  }

  function sectionOf(path) {
    const i = path.indexOf("/");
    return i < 0 ? "root" : path.slice(0, i);
  }

  function renderInline(text, onLink, keyPrefix) {
    const re = /\[\[([^\]|#]+)(?:\|([^\]]*))?\]\]|\*\*([^*]+)\*\*|`([^`]+)`/g;
    const out = [];
    let last = 0;
    let i = 0;
    let m;
    while ((m = re.exec(text)) !== null) {
      if (m.index > last) out.push(text.slice(last, m.index));
      if (m[1] !== undefined) {
        const id = m[1].trim();
        const label = (m[2] || id.split("/").pop() || id).trim();
        out.push(h("a", {
          key: keyPrefix + "-" + i,
          className: "signals-wiki-link",
          href: "#",
          title: id,
          onClick: function (e) {
            e.preventDefault();
            onLink(id);
          },
        }, label));
      } else if (m[3] !== undefined) {
        out.push(h("strong", { key: keyPrefix + "-" + i }, m[3]));
      } else {
        out.push(h("code", { key: keyPrefix + "-" + i }, m[4]));
      }
      last = re.lastIndex;
      i += 1;
    }
    if (last < text.length) out.push(text.slice(last));
    return out;
  }

  function renderBody(text, onLink) {
    const lines = (text || "").split("\n");
    const blocks = [];
    let i = 0;
    if (lines[0] && lines[0].trim() === "---") {
      i = 1;
      while (i < lines.length && lines[i].trim() !== "---") i += 1;
      if (i < lines.length) i += 1;
    }
    while (i < lines.length) {
      const ln = lines[i];
      if (ln.startsWith("```")) {
        const lang = ln.slice(3).trim();
        const buf = [];
        i += 1;
        while (i < lines.length && !lines[i].startsWith("```")) {
          buf.push(lines[i]);
          i += 1;
        }
        blocks.push(h("pre", { key: "c-" + i, className: "signals-wiki-code" }, buf.join("\n")));
        i += 1;
        continue;
      }
      if (ln.startsWith("# ")) {
        blocks.push(h("h1", { key: "h-" + i }, renderInline(ln.slice(2), onLink, "h" + i)));
        i += 1;
        continue;
      }
      if (ln.startsWith("## ")) {
        blocks.push(h("h2", { key: "h-" + i }, renderInline(ln.slice(3), onLink, "h" + i)));
        i += 1;
        continue;
      }
      if (ln.startsWith("### ")) {
        blocks.push(h("h3", { key: "h-" + i }, renderInline(ln.slice(4), onLink, "h" + i)));
        i += 1;
        continue;
      }
      if (ln.trim() === "---") {
        blocks.push(h("hr", { key: "r-" + i }));
        i += 1;
        continue;
      }
      if (ln.trim() === "") {
        i += 1;
        continue;
      }
      blocks.push(h("p", { key: "p-" + i }, renderInline(ln, onLink, "p" + i)));
      i += 1;
    }
    return blocks;
  }

  function Panel(props) {
    const note = props.note;
    const onLink = props.onLink;
    const onClose = props.onClose;
    const focused = props.focused;
    return h("article", {
      className: "signals-wiki-panel" + (focused ? " focused" : ""),
    },
      h("header", { className: "signals-wiki-panel-head" },
        h("strong", null, note ? note.title : (props.loading ? "…" : "not found")),
        h("button", {
          className: "signals-wiki-close",
          type: "button",
          title: "Close this panel",
          onClick: onClose,
        }, "×")
      ),
      note
        ? h("div", { className: "signals-wiki-panel-body" },
            h("p", { className: "signals-wiki-meta" }, note.path),
            renderBody(note.text, onLink)
          )
        : h("p", { className: "signals-wiki-meta" }, props.loading ? "loading…" : "missing")
    );
  }

  function WikiLineup() {
    const [pages, setPages] = useState([]);
    const [status, setStatus] = useState(null);
    const [trail, setTrail] = useState([]);
    const [cache, setCache] = useState({});
    const [error, setError] = useState("");
    const lastNav = useRef(null);
    const prevLen = useRef(0);
    const requested = useRef({});

    const fetchNote = useCallback(function (path) {
      if (!path || requested.current[path]) return;
      requested.current[path] = true;
      SDK.fetchJSON(API + "/page?path=" + encodeURIComponent(path))
        .then(function (n) {
          setCache(function (c) {
            const next = Object.assign({}, c);
            next[path] = n;
            return next;
          });
        })
        .catch(function () {
          setCache(function (c) {
            const next = Object.assign({}, c);
            next[path] = null;
            return next;
          });
        });
    }, []);

    useEffect(function () {
      SDK.fetchJSON(API + "/status").then(setStatus).catch(function (e) {
        setError(String(e && e.message ? e.message : e));
      });
      SDK.fetchJSON(API + "/tree").then(function (d) {
        setPages(d.pages || []);
      }).catch(function (e) {
        setError(String(e && e.message ? e.message : e));
      });
    }, []);

    useEffect(function () {
      if (!pages.length || trail.length) return;
      const saved = loadTrail();
      const paths = pages.map(function (p) { return p.path; });
      const q = new URL(window.location.href).searchParams.get("open");
      if (q && paths.indexOf(q) >= 0) {
        setTrail(saved && saved.indexOf(q) >= 0 ? saved.slice(0, saved.indexOf(q) + 1) : [q]);
        return;
      }
      if (saved && saved.every(function (p) { return paths.indexOf(p) >= 0; })) {
        setTrail(saved);
        return;
      }
      const seed = paths.indexOf("index.md") >= 0 ? "index.md"
        : (paths.indexOf("SCHEMA.md") >= 0 ? "SCHEMA.md" : paths[0]);
      setTrail(seed ? [seed] : []);
    }, [pages, trail.length]);

    useEffect(function () {
      trail.forEach(fetchNote);
      saveTrail(trail);
      if (!trail.length) return;
      const focused = trail[trail.length - 1];
      const extend = trail.length > prevLen.current;
      prevLen.current = trail.length;
      lastNav.current = focused;
      const url = new URL(window.location.href);
      url.searchParams.set("open", focused);
      window.history[extend ? "pushState" : "replaceState"]({}, "", url);
    }, [trail, fetchNote]);

    function extendTrail(fromIdx, path) {
      setTrail(function (t) {
        const base = t.slice(0, fromIdx + 1);
        const at = base.indexOf(path);
        if (at >= 0) return base.slice(0, at + 1);
        return base.concat([path]);
      });
    }

    function openFrom(fromIdx) {
      return function (target) {
        const known = pages.find(function (p) {
          return p.path === target || p.path === target + ".md";
        });
        if (known) {
          extendTrail(fromIdx, known.path);
          return;
        }
        SDK.fetchJSON(API + "/resolve?q=" + encodeURIComponent(target))
          .then(function (d) {
            if (d.path) extendTrail(fromIdx, d.path);
          })
          .catch(function (e) { setError(String(e && e.message ? e.message : e)); });
      };
    }

    function startAt(path) {
      setTrail([path]);
    }

    const sections = {};
    pages.forEach(function (p) {
      const s = sectionOf(p.path);
      if (!sections[s]) sections[s] = [];
      sections[s].push(p);
    });
    const sectionNames = Object.keys(sections).sort();

    return h("div", { className: "signals-wiki-lineup" },
      h("aside", { className: "signals-wiki-rail" },
        h("p", { className: "signals-wiki-status" },
          status
            ? ((status.pages || 0) + " notes · lineup")
            : "loading…"
        ),
        error ? h("p", { className: "signals-wiki-status" }, error) : null,
        sectionNames.map(function (sec) {
          return h("div", { key: sec, className: "signals-wiki-group" },
            h("div", { className: "signals-wiki-group-title" }, sec),
            sections[sec].map(function (p) {
              return h("button", {
                key: p.path,
                type: "button",
                className: trail[0] === p.path ? "active" : "",
                title: p.path,
                onClick: function () { startAt(p.path); },
              }, p.name.replace(/\.md$/, ""));
            })
          );
        })
      ),
      h("div", { className: "signals-wiki-strip" },
        trail.map(function (path, i) {
          return h(Panel, {
            key: path + "-" + i,
            note: Object.prototype.hasOwnProperty.call(cache, path) ? cache[path] : undefined,
            loading: !Object.prototype.hasOwnProperty.call(cache, path),
            focused: i === trail.length - 1,
            onLink: openFrom(i),
            onClose: function () {
              setTrail(function (t) {
                if (t.length <= 1) return t;
                return t.slice(0, Math.max(1, i));
              });
            },
          });
        })
      )
    );
  }

  window.__HERMES_PLUGINS__.register("signals-wiki", WikiLineup);
})();
