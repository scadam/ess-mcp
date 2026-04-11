
from __future__ import annotations

from pathlib import Path as _Path


def _read_widget(name: str) -> str:
    widget_dir = _Path(__file__).resolve().parent.parent / "ui" / "widget"
    widget_path = widget_dir / name
    if widget_path.exists():
        return widget_path.read_text(encoding="utf-8")
    return f"<html><body>{name} widget</body></html>"

# ---------------------------------------------------------------------------
# Incident List dashboard – calls list_incidents via Skybridge
# ---------------------------------------------------------------------------

INCIDENT_LIST_HTML = """\
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
        --pos: #2bd48f;
        --warn: #f0b232;
        --neg: #ff6b6b;
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
        justify-content: space-between; margin-bottom: 10px;
      }
      .title { font-size: 16px; font-weight: 600; }
      .subtitle { color: var(--muted); font-size: 12px; }
      .pill {
        font-size: 11px; color: var(--muted);
        border: 1px solid #253040; padding: 2px 8px; border-radius: 999px;
      }
      .filters {
        display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px;
      }
      .filters input, .filters select {
        background: var(--card); color: var(--text);
        border: 1px solid var(--border); border-radius: 8px;
        padding: 6px 10px; font-size: 12px; outline: none;
      }
      .filters input { flex: 1; min-width: 120px; }
      .filters select { min-width: 90px; }
      .card {
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 12px; padding: 12px; margin-bottom: 8px;
        cursor: default; transition: border-color .15s;
      }
      .card:hover { border-color: #2a3442; }
      .card-header {
        display: flex; justify-content: space-between;
        align-items: flex-start; gap: 8px;
      }
      .card-header h3 {
        margin: 0; font-size: 13px; font-weight: 600;
        flex: 1; line-height: 1.3;
      }
      .card-header .number {
        font-size: 11px; color: var(--accent);
        font-weight: 600; white-space: nowrap;
      }
      .card-meta {
        display: flex; gap: 8px; flex-wrap: wrap;
        margin-top: 6px; font-size: 11px; color: var(--muted);
      }
      .tag {
        display: inline-block; padding: 2px 6px;
        border-radius: 6px; background: #0f131a;
        border: 1px solid var(--border); font-size: 10px;
      }
      .tag.state-new { border-color: var(--accent); color: var(--accent); }
      .tag.state-in-progress,
      .tag.state-in_progress { border-color: var(--warn); color: var(--warn); }
      .tag.state-resolved { border-color: var(--pos); color: var(--pos); }
      .tag.state-closed { color: var(--muted); }
      .tag.state-on-hold,
      .tag.state-on_hold { border-color: #9966cc; color: #9966cc; }
      .tag.state-canceled { color: var(--muted); opacity: .6; }
      .tag.p1 { border-color: var(--neg); color: var(--neg); }
      .tag.p2 { border-color: var(--warn); color: var(--warn); }
      .btn {
        background: #152235; color: var(--text);
        border: 1px solid #243145; border-radius: 8px;
        padding: 7px 14px; font-size: 12px; cursor: pointer;
      }
      .btn:disabled { opacity: .5; cursor: default; }
      .footer { margin-top: 10px; display: flex; gap: 8px; }
      .loading, .error, .empty {
        text-align: center; padding: 32px 0; font-size: 13px; color: var(--muted);
      }
      .error { color: var(--neg); }
      .stat-bar {
        display: flex; gap: 12px; margin-bottom: 12px; font-size: 12px;
      }
      .stat { color: var(--muted); }
      .stat strong { color: var(--text); font-weight: 700; }
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
          <div class="title">Incidents</div>
          <div class="subtitle">ServiceNow &middot; Recent Activity</div>
        </div>
        <div style="display:flex;align-items:center;gap:8px;">
          <div class="pill" id="countPill">0 incidents</div>
          <button class="maximize-btn" id="maximizeBtn" title="Maximize"><svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M10 2h4v4M6 14H2v-4M14 2L9.5 6.5M2 14l4.5-4.5"/></svg></button>
        </div>
      </div>

      <div class="filters">
        <input type="text" id="searchInput" placeholder="Search incidents&hellip;" />
        <select id="stateFilter">
          <option value="">All states</option>
          <option value="new">New</option>
          <option value="in_progress">In Progress</option>
          <option value="on_hold">On Hold</option>
          <option value="resolved">Resolved</option>
          <option value="closed">Closed</option>
        </select>
        <button class="btn" id="searchBtn">Search</button>
      </div>

      <div id="statBar" class="stat-bar"></div>
      <div id="list"></div>

      <div class="footer">
        <button class="btn" id="refreshBtn">Refresh</button>
      </div>
    </div>

    <script>
      /* ---- Skybridge helpers ---- */
      async function callTool(name, args) {
        if (window.openai && typeof window.openai.callTool === "function") {
          return window.openai.callTool(name, args || {});
        }
        if (window.ai && window.ai.tools && typeof window.ai.tools.call === "function") {
          return window.ai.tools.call({ server: "servicenow", tool: name, arguments: args || {} });
        }
        throw new Error("No Skybridge available (window.openai / window.ai)");
      }

      function extract(response) {
        if (!response) return null;
        if (response.structuredContent) return response.structuredContent;
        if (response.incidents) return response;
        if (response.result) return response.result;
        var blocks = response.content || [];
        for (var i = 0; i < blocks.length; i++) {
          if (blocks[i] && blocks[i].text) {
            try { return JSON.parse(blocks[i].text); } catch(_) {}
          }
        }
        if (window.openai && window.openai.toolOutput)
          return window.openai.toolOutput;
        return null;
      }

      function esc(s) { var d = document.createElement("div"); d.textContent = s || ""; return d.innerHTML; }

      function stateClass(state) {
        return "tag state-" + (state || "").toLowerCase().replace(/\\s+/g, "-");
      }

      function priorityClass(p) {
        if (!p) return "tag";
        var n = parseInt(p, 10);
        if (isNaN(n)) {
          if (p.toLowerCase().indexOf("critical") >= 0) return "tag p1";
          if (p.toLowerCase().indexOf("high") >= 0) return "tag p2";
          return "tag";
        }
        if (n <= 1) return "tag p1";
        if (n <= 2) return "tag p2";
        return "tag";
      }

      function renderCard(inc) {
        var meta = [];
        if (inc.priority) meta.push('<span class="' + priorityClass(inc.priority) + '">P' + esc(String(inc.priority)) + '</span>');
        if (inc.state) meta.push('<span class="' + stateClass(inc.state) + '">' + esc(inc.state) + '</span>');
        if (inc.category) meta.push('<span class="tag">' + esc(inc.category) + '</span>');
        if (inc.assigned_to) meta.push('<span>' + esc(inc.assigned_to) + '</span>');
        if (inc.opened_at) meta.push('<span>' + esc(inc.opened_at) + '</span>');

        return '<div class="card">' +
          '<div class="card-header">' +
            '<h3>' + esc(inc.short_description || "(no description)") + '</h3>' +
            '<span class="number">' + esc(inc.number || "") + '</span>' +
          '</div>' +
          '<div class="card-meta">' + meta.join("") + '</div>' +
        '</div>';
      }

      function renderStats(incidents) {
        var states = {};
        incidents.forEach(function(inc) {
          var s = inc.state || "Unknown";
          states[s] = (states[s] || 0) + 1;
        });
        var html = "";
        Object.keys(states).sort().forEach(function(s) {
          html += '<span class="stat"><strong>' + states[s] + '</strong> ' + esc(s) + '</span>';
        });
        document.getElementById("statBar").innerHTML = html;
      }

      var listDiv = document.getElementById("list");
      var countPill = document.getElementById("countPill");

      async function load(search, state) {
        listDiv.innerHTML = '<div class="loading">Loading incidents&hellip;</div>';
        try {
          var args = { limit: 20 };
          if (search) args.search_text = search;
          if (state) args.state = state;
          var response = await callTool("list_incidents", args);
          var data = extract(response);
          var incidents = (data && data.incidents) || [];
          countPill.textContent = incidents.length + " incident" + (incidents.length !== 1 ? "s" : "");
          if (incidents.length === 0) {
            listDiv.innerHTML = '<div class="empty">No incidents found.</div>';
            document.getElementById("statBar").innerHTML = "";
            return;
          }
          renderStats(incidents);
          listDiv.innerHTML = incidents.map(renderCard).join("");
        } catch (err) {
          listDiv.innerHTML = '<div class="error">' + esc(err.message || "Failed to load incidents") + '</div>';
        } finally {
          reportHeight();
        }
      }

      document.getElementById("searchBtn").addEventListener("click", function() {
        load(document.getElementById("searchInput").value, document.getElementById("stateFilter").value);
      });
      document.getElementById("searchInput").addEventListener("keydown", function(e) {
        if (e.key === "Enter") load(this.value, document.getElementById("stateFilter").value);
      });
      document.getElementById("refreshBtn").addEventListener("click", function() {
        document.getElementById("searchInput").value = "";
        document.getElementById("stateFilter").value = "";
        load();
      });

      /* ---- Display Mode (maximize / restore) ---- */
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

      /* Auto-load */
      if (window.openai && window.openai.toolOutput) {
        var pre = window.openai.toolOutput;
        if (pre && pre.incidents) {
          countPill.textContent = pre.incidents.length + " incident" + (pre.incidents.length !== 1 ? "s" : "");
          renderStats(pre.incidents);
          listDiv.innerHTML = pre.incidents.map(renderCard).join("");
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
SERVICENOW_RESOURCES = {
    "incident-list": {
        "description": "Interactive incident list dashboard – calls list_incidents via Skybridge with search and state filtering.",
        "mime_type": "text/html+skybridge",
        "content": INCIDENT_LIST_HTML,
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
    "create-incident": {
        "description": "Incident creation form – calls create_incident via Skybridge with caller, description, category, urgency, and impact fields.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("create-incident.html"),
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
    "team-incidents": {
        "description": "Team incident workload dashboard – calls get_team_incidents via Skybridge showing priority breakdown, assignee workload, and recent incidents.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("team-incidents.html"),
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
    "create-change-request": {
        "description": "Change request creation/update form – create or update ServiceNow change requests with type, risk, impact, and scheduling fields.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("create-change-request.html"),
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
    "create-problem": {
        "description": "Problem creation/update form – create or update ServiceNow problem records with category, priority, impact, and urgency fields.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("create-problem.html"),
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
    "update-incident": {
        "description": "Incident update form – edit an existing ServiceNow incident with pre-filled values for state, priority, assignment, and work notes.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("update-incident.html"),
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
    "update-task": {
        "description": "Task update form – edit a ServiceNow task with state, priority, assignment, and comments.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("update-task.html"),
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
    "approval-review": {
        "description": "Approval review widget – view pending approvals and approve or reject them directly.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("approval-review.html"),
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
    "catalog-list": {
        "description": "Service catalog list – browse available catalog items with search and category filtering.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("catalog-list.html"),
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
    "catalog-item": {
        "description": "Catalog item detail – view and order a specific service catalog item with configuration options.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("catalog-item.html"),
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
    "cart-summary": {
        "description": "Shopping cart summary – review items in the cart, adjust quantities, and proceed to checkout.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("cart-summary.html"),
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
    "task-list": {
        "description": "Task list dashboard – view and manage ServiceNow tasks and approvals with filtering by state and priority.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("task-list.html"),
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
}
