(function () {
  "use strict";

  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK || !window.__HERMES_PLUGINS__) return;

  const React = SDK.React;
  const { useState, useEffect } = SDK.hooks;
  const API = "/api/plugins/signals-wiki";

  function h(type, props) {
    const children = Array.prototype.slice.call(arguments, 2);
    return React.createElement.apply(React, [type, props].concat(children));
  }

  function WikiPage() {
    const [status, setStatus] = useState(null);
    const [pages, setPages] = useState([]);
    const [current, setCurrent] = useState("");
    const [doc, setDoc] = useState(null);
    const [error, setError] = useState("");

    useEffect(function () {
      SDK.fetchJSON(API + "/status")
        .then(setStatus)
        .catch(function (e) { setError(String(e && e.message ? e.message : e)); });
      SDK.fetchJSON(API + "/tree")
        .then(function (d) { setPages(d.pages || []); })
        .catch(function (e) { setError(String(e && e.message ? e.message : e)); });
    }, []);

    function openPage(path) {
      setCurrent(path);
      setError("");
      SDK.fetchJSON(API + "/page?path=" + encodeURIComponent(path))
        .then(setDoc)
        .catch(function (e) { setError(String(e && e.message ? e.message : e)); setDoc(null); });
    }

    return h("div", { className: "signals-wiki" },
      h("aside", { className: "signals-wiki-tree" },
        h("p", { className: "signals-wiki-status" },
          status
            ? ((status.pages || 0) + " pages · " + (status.rustfs ? "rustfs " + status.bucket + "/" + status.prefix : "vault only"))
            : "loading…"
        ),
        pages.map(function (p) {
          return h("button", {
            key: p.path,
            className: current === p.path ? "active" : "",
            onClick: function () { openPage(p.path); },
            title: p.path,
          }, p.path);
        })
      ),
      h("article", { className: "signals-wiki-body" },
        error ? h("p", { className: "signals-wiki-status" }, error) : null,
        doc
          ? h("div", null,
              h("p", { className: "signals-wiki-meta" }, doc.path + " · " + doc.bytes + " B · " + (doc.object || "")),
              h("pre", null, doc.text)
            )
          : h("p", { className: "signals-wiki-status" }, "Select a note.")
      )
    );
  }

  window.__HERMES_PLUGINS__.register("signals-wiki", WikiPage);
})();
