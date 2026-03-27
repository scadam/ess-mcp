"""Workday MCP resource definitions – self-contained HTML+Skybridge widgets."""

from __future__ import annotations

from pathlib import Path as _Path

def _read_widget(name: str) -> str:
    """Read a widget HTML file from the ui/widget directory."""
    widget_dir = _Path(__file__).resolve().parent.parent / "ui" / "widget"
    return (widget_dir / name).read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# Worker Profile card – single-file HTML widget
# Uses the OpenAI Skybridge (window.openai) to call the `get_worker` MCP tool
# and render a profile card.  Falls back to window.ai.tools.call for compat.
# ---------------------------------------------------------------------------

WORKER_PROFILE_HTML = """\
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>
      :root {
        --bg: #0b0f14;
        --card: #151a21;
        --muted: #a9b1bd;
        --text: #e6edf3;
        --accent: #4cc2ff;
        --border: #1f2630;
      }
      html, body { height: 100%; background: var(--bg); }
      body {
        margin: 0;
        font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
        color: var(--text);
        background: var(--bg);
      }
      .wrap { padding: 16px; min-height: 100%; box-sizing: border-box; }
      .header {
        display: flex; align-items: center;
        justify-content: space-between; margin-bottom: 14px;
      }
      .title { font-size: 16px; font-weight: 600; }
      .subtitle { color: var(--muted); font-size: 12px; }
      .card {
        background: radial-gradient(900px 260px at 10% -10%,
          rgba(76,194,255,.16), transparent 55%), var(--card);
        border: 1px solid #2a3442;
        border-radius: 14px; padding: 18px;
        box-shadow: 0 8px 20px rgba(0,0,0,.3);
      }
      .identity { display: flex; align-items: center; gap: 14px; margin-bottom: 16px; }
      .avatar {
        width: 52px; height: 52px; border-radius: 50%;
        background: linear-gradient(135deg, var(--accent), #6366f1);
        display: flex; align-items: center; justify-content: center;
        font-weight: 700; font-size: 18px; color: #fff;
        flex-shrink: 0;
      }
      .identity h2 { margin: 0; font-size: 18px; font-weight: 700; }
      .identity p  { margin: 2px 0 0; font-size: 13px; color: var(--muted); }
      .identity a  { color: var(--accent); font-size: 12px; text-decoration: none; }
      .identity a:hover { text-decoration: underline; }
      .grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 12px;
      }
      .field {}
      .label { margin: 0; font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .5px; }
      .value { margin: 4px 0 0; font-size: 13px; font-weight: 500; }
      .btn {
        margin-top: 14px;
        background: #152235; color: var(--text);
        border: 1px solid #243145; border-radius: 8px;
        padding: 7px 14px; font-size: 12px; cursor: pointer;
      }
      .btn:disabled { opacity: .5; cursor: default; }
      .loading, .error, .empty {
        text-align: center; padding: 32px 0; font-size: 13px; color: var(--muted);
      }
      .error { color: #ff6b6b; }
      .footer {
        margin-top: 12px; font-size: 11px; color: var(--muted); text-align: right;
      }
      .maximize-btn {
        background: transparent; color: var(--muted);
        border: 1px solid var(--border); border-radius: 8px;
        padding: 4px 8px; cursor: pointer;
        display: flex; align-items: center; justify-content: center;
        transition: color .15s, border-color .15s;
      }
      .maximize-btn:hover { color: var(--accent); border-color: var(--accent); }
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="header">
        <div>
          <div class="title">Worker Profile</div>
          <div class="subtitle">Workday &middot; Employee Details</div>
        </div>
        <button class="maximize-btn" id="maximizeBtn" title="Maximize"><svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M10 2h4v4M6 14H2v-4M14 2L9.5 6.5M2 14l4.5-4.5"/></svg></button>
      </div>
      <div id="content"><div class="loading">Loading worker profile&hellip;</div></div>
      <button class="btn" id="refreshBtn">Refresh</button>
      <div class="footer">Powered by <strong>workday / get_worker</strong> via MCP</div>
    </div>

    <script>
      /* ---- Skybridge helpers ---- */
      async function callTool(name, args) {
        if (window.openai && typeof window.openai.callTool === "function") {
          return window.openai.callTool(name, args || {});
        }
        if (window.ai && window.ai.tools && typeof window.ai.tools.call === "function") {
          return window.ai.tools.call({ server: "workday", tool: name, arguments: args || {} });
        }
        throw new Error("No Skybridge available (window.openai / window.ai)");
      }

      function extractWorker(response) {
        if (!response) return null;
        if (response.structuredContent) {
          return response.structuredContent;
        }
        if (response.worker_id || response.full_name) return response;
        if (response.result) return response.result;
        var blocks = response.content || [];
        for (var i = 0; i < blocks.length; i++) {
          if (blocks[i] && blocks[i].text) {
            try { return JSON.parse(blocks[i].text); } catch(_) {}
          }
        }
        if (window.openai && window.openai.toolOutput) {
          return window.openai.toolOutput;
        }
        return null;
      }

      function initials(name) {
        return (name || "?").split(" ").map(function(p) { return p[0]; }).join("").slice(0, 2);
      }

      function field(label, value) {
        return '<div class="field">' +
          '<p class="label">' + label + '</p>' +
          '<p class="value">' + (value || "\\u2014") + '</p>' +
          '</div>';
      }

      function renderCard(w) {
        var email = w.email || "";
        var emailLink = email
          ? '<a href="mailto:' + email + '">' + email + '</a>'
          : "";
        var location = w.location || "";
        if (w.locationId) location += location ? " (" + w.locationId + ")" : w.locationId;
        var country = w.country || "";
        if (w.countryCode) country += country ? " (" + w.countryCode + ")" : w.countryCode;
        var job = w.jobProfile || "";
        if (w.jobType) job += job ? " \\u00b7 " + w.jobType : w.jobType;
        var primaryJob = w.primaryJobDescriptor || "";
        if (w.primaryJobId) primaryJob += primaryJob ? " (" + w.primaryJobId + ")" : w.primaryJobId;

        return '<div class="card">' +
          '<div class="identity">' +
            '<div class="avatar">' + initials(w.name || w.descriptor || "?") + '</div>' +
            '<div>' +
              '<h2>' + (w.name || w.descriptor || "Unknown") + '</h2>' +
              '<p>' + (w.businessTitle || "") + '</p>' +
              emailLink +
            '</div>' +
          '</div>' +
          '<div class="grid">' +
            field("Workday ID", w.workdayId || w.id) +
            field("Worker ID", w.workerId) +
            field("Worker Type", w.workerType) +
            field("Location", location) +
            field("Country", country) +
            field("Organization", w.supervisoryOrganization) +
            field("Job Profile", job) +
            field("Primary Job", primaryJob) +
          '</div>' +
        '</div>';
      }

      var contentDiv = document.getElementById("content");
      var refreshBtn = document.getElementById("refreshBtn");

      async function load() {
        contentDiv.innerHTML = '<div class="loading">Loading worker profile&hellip;</div>';
        refreshBtn.disabled = true;
        try {
          var response = await callTool("get_worker", {});
          var worker = extractWorker(response);
          if (worker) {
            contentDiv.innerHTML = renderCard(worker);
          } else {
            contentDiv.innerHTML = '<div class="empty">No worker data returned.</div>';
          }
        } catch (err) {
          contentDiv.innerHTML = '<div class="error">' + (err.message || "Failed to load profile") + '</div>';
        } finally {
          refreshBtn.disabled = false;
          reportHeight();
        }
      }

      refreshBtn.addEventListener("click", load);

      var _expandSvg = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M10 2h4v4M6 14H2v-4M14 2L9.5 6.5M2 14l4.5-4.5"/></svg>';
      var _collapseSvg = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 6h-4V2M2 10h4v4M10 6l4.5-4.5M6 10L1.5 14.5"/></svg>';
      var _isFullscreen = false;
      var _maxBtn = document.getElementById("maximizeBtn");

      function reportHeight() {
        if (window.openai && typeof window.openai.notifyIntrinsicHeight === "function") {
          window.openai.notifyIntrinsicHeight(document.body.scrollHeight);
        }
      }

      function _applyFullscreenLayout() {
        var root = document.querySelector(".wrap");
        if (window.openai) {
          if (window.openai.maxHeight) { root.style.height = window.openai.maxHeight + "px"; root.style.overflow = "auto"; }
          var sa = window.openai.safeArea;
          if (sa && sa.insets) {
            root.style.paddingTop = (sa.insets.top || 16) + "px";
            root.style.paddingBottom = (sa.insets.bottom || 16) + "px";
            root.style.paddingLeft = (sa.insets.left || 16) + "px";
            root.style.paddingRight = (sa.insets.right || 16) + "px";
          }
        }
      }

      function _resetLayout() {
        var root = document.querySelector(".wrap");
        root.style.height = ""; root.style.overflow = "";
        root.style.paddingTop = ""; root.style.paddingBottom = "";
        root.style.paddingLeft = ""; root.style.paddingRight = "";
      }

      async function toggleFullscreen() {
        if (!window.openai || typeof window.openai.requestDisplayMode !== "function") return;
        var mode = _isFullscreen ? "inline" : "fullscreen";
        try {
          await window.openai.requestDisplayMode({ mode: mode });
          _isFullscreen = !_isFullscreen;
          _maxBtn.innerHTML = _isFullscreen ? _collapseSvg : _expandSvg;
          _maxBtn.title = _isFullscreen ? "Restore" : "Maximize";
          if (_isFullscreen) _applyFullscreenLayout(); else _resetLayout();
          reportHeight();
        } catch (e) { /* host denied the mode switch */ }
      }

      if (_maxBtn) {
        if (window.openai && typeof window.openai.requestDisplayMode === "function") {
          _maxBtn.addEventListener("click", toggleFullscreen);
        } else {
          _maxBtn.style.display = "none";
        }
      }

      if (window.openai && window.openai.toolOutput) {
        var preloaded = window.openai.toolOutput;
        if (preloaded && typeof preloaded === "object") {
          contentDiv.innerHTML = renderCard(preloaded);
        } else {
          load();
        }
      } else {
        load();
      }
    </script>
  </body>
</html>
"""

# ---------------------------------------------------------------------------
# Registry: map of resource name → (description, mime_type, content)
# ---------------------------------------------------------------------------
WORKDAY_RESOURCES = {
    "worker-profile": {
        "description": "Interactive worker profile card – calls get_worker via Skybridge and renders an employee details widget.",
        "mime_type": "text/html+skybridge",
        "content": WORKER_PROFILE_HTML,
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
    "leave-booking": {
        "description": "Leave booking widget – calendar view of booked PTO, balance chips, and a form to request time off via book_leave.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("leave-booking.html"),
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
}
