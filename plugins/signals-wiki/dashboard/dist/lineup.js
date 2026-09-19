(function () {
  "use strict";

  // Lineup of filesystem positions then notes (Ægir panel width). Not a
  // federated wiki.
  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK || !window.__HERMES_PLUGINS__) return;

  const React = SDK.React;
  const { useState, useEffect, useRef, useCallback } = SDK.hooks;
  const API = "/api/plugins/signals-wiki";
  const TRAIL_KEY = "hermes-wiki:lineup-v2";

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
      sessionStorage.setItem(TRAIL_KEY, JSON.stringify(trail));
    } catch (_e) {}
  }

  function listingKey(item) {
    return ["L", item.root, item.path || "", String(item.offset || 0)].join(":");
  }

  function itemKey(item, i) {
    if (item.kind === "page") return "P:" + item.path + ":" + i;
    return listingKey(item) + ":" + i;
  }

  function renderInline(text, onLink, keyPrefix) {
    const re = /\[\[([^\]|#]+)(?:\|([^\]]*))?\]\]|\*\*([^*]+)\*\*|`([^`]+)`/g;
    const out = [];
    let last = 0;
    let n = 0;
    let m;
    while ((m = re.exec(text)) !== null) {
      if (m.index > last) out.push(text.slice(last, m.index));
      if (m[1] !== undefined) {
        const id = m[1].trim();
        const label = (m[2] || id.split("/").pop() || id).trim();
        out.push(h("a", {
          key: keyPrefix + "-" + n,
          className: "signals-wiki-link",
          href: "#",
          title: id,
          onClick: function (e) {
            e.preventDefault();
            onLink(id);
          },
        }, label));
      } else if (m[3] !== undefined) {
        out.push(h("strong", { key: keyPrefix + "-" + n }, m[3]));
      } else {
        out.push(h("code", { key: keyPrefix + "-" + n }, m[4]));
      }
      last = re.lastIndex;
      n += 1;
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
      } else if (ln.startsWith("## ")) {
        blocks.push(h("h2", { key: "h-" + i }, renderInline(ln.slice(3), onLink, "h" + i)));
      } else if (ln.startsWith("### ")) {
        blocks.push(h("h3", { key: "h-" + i }, renderInline(ln.slice(4), onLink, "h" + i)));
      } else if (ln.trim() === "---") {
        blocks.push(h("hr", { key: "r-" + i }));
      } else if (ln.trim() !== "") {
        blocks.push(h("p", { key: "p-" + i }, renderInline(ln, onLink, "p" + i)));
      }
      i += 1;
    }
    return blocks;
  }

  function ListingPanel(props) {
    const data = props.data;
    const onOpen = props.onOpen;
    const onMore = props.onMore;
    const onClose = props.onClose;
    const title = (data && (data.vault_path || data.root) || "…");
    const entries = (data && data.entries) || [];
    return h("article", { className: "signals-wiki-panel" + (props.focused ? " focused" : "") },
      h("header", { className: "signals-wiki-panel-head" },
        h("strong", null, title || data.root),
        h("span", { className: "signals-wiki-meta" },
          data ? ((data.offset || 0) + 1) + "–" + ((data.offset || 0) + entries.length) + " of " + data.total : ""
        ),
        h("button", { className: "signals-wiki-close", type: "button", onClick: onClose }, "×")
      ),
      h("div", { className: "signals-wiki-panel-body" },
        !data ? h("p", { className: "signals-wiki-meta" }, "loading…") : null,
        entries.map(function (e) {
          return h("button", {
            key: e.path,
            type: "button",
            className: "signals-wiki-entry signals-wiki-entry-" + e.kind,
            onClick: function () { onOpen(e); },
          },
            h("span", { className: "signals-wiki-entry-name" }, e.kind === "dir" ? e.name + "/" : e.name),
            h("span", { className: "signals-wiki-entry-kind" }, e.kind)
          );
        }),
        data && data.more
          ? h("button", {
              type: "button",
              className: "signals-wiki-entry signals-wiki-more",
              onClick: onMore,
            }, "more…")
          : null,
        data && entries.length === 0
          ? h("p", { className: "signals-wiki-meta" }, "empty")
          : null
      )
    );
  }

  function PagePanel(props) {
    const note = props.note;
    return h("article", { className: "signals-wiki-panel" + (props.focused ? " focused" : "") },
      h("header", { className: "signals-wiki-panel-head" },
        h("strong", null, note ? note.title : (props.loading ? "…" : "not found")),
        h("button", { className: "signals-wiki-close", type: "button", onClick: props.onClose }, "×")
      ),
      note
        ? h("div", { className: "signals-wiki-panel-body" },
            h("p", { className: "signals-wiki-meta" }, note.path),
            renderBody(note.text, props.onLink)
          )
        : h("p", { className: "signals-wiki-meta" }, props.loading ? "loading…" : "missing")
    );
  }

  function WikiLineup() {
    const [rail, setRail] = useState(null);
    const [trail, setTrail] = useState([]);
    const [listings, setListings] = useState({});
    const [pages, setPages] = useState({});
    const [error, setError] = useState("");
    const prevLen = useRef(0);
    const requested = useRef({});

    useEffect(function () {
      SDK.fetchJSON(API + "/rail")
        .then(setRail)
        .catch(function (e) { setError(String(e && e.message ? e.message : e)); });
      const saved = loadTrail();
      if (saved && saved.length) setTrail(saved);
    }, []);

    const listingId = useCallback(function (item) {
      return listingKey(item);
    }, []);

    useEffect(function () {
      trail.forEach(function (item) {
        if (item.kind === "listing") {
          const id = listingId(item);
          if (requested.current[id]) return;
          requested.current[id] = true;
          const q = "root=" + encodeURIComponent(item.root)
            + "&path=" + encodeURIComponent(item.path || "")
            + "&offset=" + encodeURIComponent(item.offset || 0);
          SDK.fetchJSON(API + "/listing?" + q)
            .then(function (d) {
              setListings(function (c) {
                const n = Object.assign({}, c);
                n[id] = d;
                return n;
              });
            })
            .catch(function (e) { setError(String(e && e.message ? e.message : e)); });
        } else if (item.kind === "page" && item.path) {
          const pk = "P:" + item.path;
          if (requested.current[pk]) return;
          requested.current[pk] = true;
          SDK.fetchJSON(API + "/page?path=" + encodeURIComponent(item.path))
            .then(function (d) {
              setPages(function (c) {
                const n = Object.assign({}, c);
                n[item.path] = d;
                return n;
              });
            })
            .catch(function () {
              setPages(function (c) {
                const n = Object.assign({}, c);
                n[item.path] = null;
                return n;
              });
            });
        }
      });
      saveTrail(trail);
      if (!trail.length) return;
      const focused = trail[trail.length - 1];
      const extend = trail.length > prevLen.current;
      prevLen.current = trail.length;
      const url = new URL(window.location.href);
      if (focused.kind === "page") url.searchParams.set("open", focused.path);
      else url.searchParams.set("open", listingId(focused));
      window.history[extend ? "pushState" : "replaceState"]({}, "", url);
    }, [trail, listingId]);

    function sliceTo(fromIdx, next) {
      setTrail(function (t) { return t.slice(0, fromIdx + 1).concat([next]); });
    }

    function startRoot(root) {
      setTrail([{ kind: "listing", root: root, path: "", offset: 0 }]);
    }

    function openEntry(fromIdx, root, entry) {
      if (entry.kind === "dir") {
        sliceTo(fromIdx, { kind: "listing", root: root, path: entry.path, offset: 0 });
        return;
      }
      sliceTo(fromIdx, { kind: "page", path: entry.vault_path || entry.path });
    }

    function openMore(fromIdx, listing) {
      sliceTo(fromIdx, {
        kind: "listing",
        root: listing.root,
        path: listing.path || "",
        offset: listing.next_offset || 0,
      });
    }

    function openWikilink(fromIdx) {
      return function (target) {
        SDK.fetchJSON(API + "/resolve?q=" + encodeURIComponent(target))
          .then(function (d) {
            if (d.path) sliceTo(fromIdx, { kind: "page", path: d.path });
          })
          .catch(function (e) { setError(String(e && e.message ? e.message : e)); });
      };
    }

    const sections = (rail && rail.sections) || [];

    return h("div", { className: "signals-wiki-lineup" },
      h("aside", { className: "signals-wiki-rail" },
        h("p", { className: "signals-wiki-status" }, "Archive / Current / Scratch"),
        error ? h("p", { className: "signals-wiki-status" }, error) : null,
        sections.map(function (sec) {
          return h("div", { key: sec.id, className: "signals-wiki-group" },
            h("button", {
              type: "button",
              className: "signals-wiki-root" + (trail[0] && trail[0].root === sec.id ? " active" : ""),
              onClick: function () { startRoot(sec.id); },
            }, sec.label),
            (sec.recent || []).map(function (e) {
              return h("button", {
                key: e.path,
                type: "button",
                className: "signals-wiki-recent",
                title: e.vault_path || e.path,
                onClick: function () {
                  const listing = { kind: "listing", root: sec.id, path: "", offset: 0 };
                  if (e.kind === "dir") {
                    setTrail([listing, { kind: "listing", root: sec.id, path: e.path, offset: 0 }]);
                  } else {
                    setTrail([listing, { kind: "page", path: e.vault_path || e.path }]);
                  }
                },
              }, e.name.replace(/\.md$/, ""));
            }),
            sec.more
              ? h("button", {
                  type: "button",
                  className: "signals-wiki-recent signals-wiki-more",
                  onClick: function () { startRoot(sec.id); },
                }, "more…")
              : null
          );
        })
      ),
      h("div", { className: "signals-wiki-strip" },
        trail.map(function (item, i) {
          const close = function () {
            setTrail(function (t) {
              if (t.length <= 1) return t;
              return t.slice(0, Math.max(1, i));
            });
          };
          if (item.kind === "listing") {
            return h(ListingPanel, {
              key: itemKey(item, i),
              data: listings[listingId(item)],
              focused: i === trail.length - 1,
              onOpen: function (entry) { openEntry(i, item.root, entry); },
              onMore: function () {
                const data = listings[listingId(item)];
                if (data) openMore(i, data);
              },
              onClose: close,
            });
          }
          return h(PagePanel, {
            key: itemKey(item, i),
            note: Object.prototype.hasOwnProperty.call(pages, item.path) ? pages[item.path] : undefined,
            loading: !Object.prototype.hasOwnProperty.call(pages, item.path),
            focused: i === trail.length - 1,
            onLink: openWikilink(i),
            onClose: close,
          });
        })
      )
    );
  }

  window.__HERMES_PLUGINS__.register("signals-wiki", WikiLineup);
})();
