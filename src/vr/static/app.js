/* DCS Command Palette — web UI logic
 *
 * Talks to the Python HTTP server on the same origin (http://127.0.0.1:<port>/).
 * The flow mirrors the desktop overlay:
 *   - type → /api/search → list rows
 *   - click a row → either execute immediately (toggle/momentary/keyboard)
 *                   or expand an inline submenu (multi-position, stepper,
 *                   string input, spring-loaded)
 *   - click the star → /api/favorite (toggles), then re-run search
 *
 * Designed for mouse-only input via OpenKneeboard's cursor.  Keyboard in
 * the WebView2 tab is unreliable so we avoid shortcuts.
 */
(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const searchInput = $("#search");
  const resultsEl = $("#results");
  const biosDot = $("#bios-dot");
  const toastEl = $("#toast");

  let lastResults = [];
  let expandedId = null;   // identifier of row currently showing submenu
  let selectedIdx = 0;
  let searchTimer = null;
  let toastTimer = null;

  // ── Networking helpers ──────────────────────────────────────
  async function apiGet(path) {
    const r = await fetch(path, { cache: "no-store" });
    if (!r.ok) throw new Error(`GET ${path} → ${r.status}`);
    return r.json();
  }
  async function apiPost(path, body) {
    const r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    if (!r.ok) throw new Error(`POST ${path} → ${r.status}`);
    return r.json();
  }

  // ── UI helpers ──────────────────────────────────────────────
  function toast(msg, kind) {
    toastEl.textContent = msg;
    toastEl.className = kind || "";
    toastEl.classList.remove("hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      toastEl.classList.add("hidden");
    }, 1800);
  }

  function htmlEscape(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // Briefly paint an overlay label on a specific row, e.g. "ON" / "PRESSED".
  // Used because OpenKneeboard's WebView2 doesn't show PyQt-style animations,
  // but users still need visible confirmation that a toggle fired.
  function flashRow(identifier, text, kind) {
    const row = resultsEl.querySelector(
      `.row[data-identifier="${cssEscape(identifier)}"]`,
    );
    if (!row) return;
    let badge = row.querySelector(".state-badge");
    if (!badge) {
      badge = document.createElement("div");
      badge.className = "state-badge";
      row.appendChild(badge);
    }
    badge.textContent = text;
    badge.className = "state-badge show" + (kind ? " " + kind : "");
    clearTimeout(badge._t);
    badge._t = setTimeout(() => {
      badge.classList.remove("show");
    }, 1200);
  }

  function cssEscape(s) {
    // Minimal — our identifiers are ASCII [A-Z0-9_] so just quote-escape
    return String(s).replace(/"/g, '\\"');
  }

  // Predict the textual state for a toggle given the numeric response value
  function toggleLabel(cmd, val) {
    const labels = cmd.position_labels;
    if (labels) {
      const k = String(val || 0);
      if (labels[k]) return labels[k];
    }
    return val ? "ON" : "OFF";
  }

  // ── Search ─────────────────────────────────────────────────
  async function runSearch(q) {
    try {
      const data = await apiGet("/api/search?q=" + encodeURIComponent(q || ""));
      lastResults = data.results || [];
      selectedIdx = 0;
      expandedId = null;
      renderResults();
    } catch (e) {
      console.error(e);
      toast("Search failed", "err");
    }
  }

  function scheduleSearch() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => runSearch(searchInput.value), 40);
  }

  // ── Rendering ──────────────────────────────────────────────
  function renderResults() {
    if (!lastResults.length) {
      resultsEl.innerHTML =
        '<div class="empty">No matches — try a different search.</div>';
      return;
    }
    const frag = document.createDocumentFragment();
    lastResults.forEach((cmd, i) => {
      frag.appendChild(renderRow(cmd, i));
      if (cmd.identifier === expandedId) {
        frag.appendChild(renderSubmenu(cmd));
      }
    });
    resultsEl.innerHTML = "";
    resultsEl.appendChild(frag);
  }

  function metaLineFor(cmd) {
    const parts = [];
    if (cmd.category) parts.push(htmlEscape(cmd.category));
    if (cmd.key_combo) parts.push(`<span class="combo">${htmlEscape(cmd.key_combo)}</span>`);
    return parts.join(" · ");
  }

  function renderRow(cmd, i) {
    const row = document.createElement("div");
    row.className = "row" + (i === selectedIdx ? " selected" : "");
    row.dataset.identifier = cmd.identifier;
    row.innerHTML = `
      <div class="row-main">
        <div class="row-desc">${htmlEscape(cmd.description)}</div>
        <div class="row-meta">${metaLineFor(cmd)}</div>
      </div>
      <div class="star${cmd.favorite ? " on" : ""}" title="Toggle favorite">
        ${cmd.favorite ? "★" : "☆"}
      </div>
    `;
    row.addEventListener("click", (ev) => onRowClick(ev, cmd, i));
    return row;
  }

  // ── Submenu renderers ──────────────────────────────────────
  // Threshold above which we show inc/dec buttons instead of one button per
  // position.  Cockpit dimmers typically have max_value = 65535; small
  // selectors cap at 4–5.  Anything beyond ~12 gets a stepper UI.
  const POSITION_BUTTON_LIMIT = 12;

  function renderSubmenu(cmd) {
    const el = document.createElement("div");
    el.className = "submenu";

    const labelCount = cmd.position_labels
      ? Object.keys(cmd.position_labels).length : 0;
    const hasLabels = labelCount > 0;
    const max = cmd.max_value;
    const smallRange = max != null && max >= 1 && max <= POSITION_BUTTON_LIMIT;

    // Show named position buttons when labels are known OR when the range
    // is small enough to fit on screen.
    if (hasLabels || smallRange) {
      const labels = cmd.position_labels || {};
      const positionCount = hasLabels ? labelCount : (max + 1);
      for (let pos = 0; pos < positionCount; pos++) {
        const name = labels[String(pos)] || `Position ${pos}`;
        const b = document.createElement("button");
        b.textContent = name;
        b.dataset.pos = String(pos);
        if (cmd.is_spring_loaded && pos === 1) {
          b.classList.add("current");
          b.textContent += " (center)";
        }
        b.addEventListener("click", (ev) => {
          ev.stopPropagation();
          onPositionClick(cmd, pos, b);
        });
        el.appendChild(b);
      }
      if (cmd.is_spring_loaded) {
        const hint = document.createElement("div");
        hint.className = "submenu-hint";
        hint.textContent =
          "Spring-loaded: tap an off-center position to engage, then tap center to release.";
        el.appendChild(hint);
      }
    }
    // Stepper (inc/dec) — dimmers, variable-step controls, and large-range
    // selectors without named positions.
    else if (cmd.has_fixed_step || cmd.has_variable_step
             || (max != null && max > POSITION_BUTTON_LIMIT)) {
      // 1. Preset % buttons — fastest way to get to a useful level
      if (max != null && max > POSITION_BUTTON_LIMIT) {
        const presets = [
          { label: "Off",   pct: 0 },
          { label: "25 %",  pct: 0.25 },
          { label: "50 %",  pct: 0.50 },
          { label: "75 %",  pct: 0.75 },
          { label: "Max",   pct: 1.0 },
        ];
        presets.forEach((p) => {
          const b = document.createElement("button");
          b.textContent = p.label;
          b.addEventListener("click", (ev) => {
            ev.stopPropagation();
            const v = Math.round(max * p.pct);
            execute(cmd.identifier, { action: "set_state", value: v })
              .then(() => flashRow(cmd.identifier, p.label, "ok"))
              .catch(() => flashRow(cmd.identifier, "ERR", "err"));
          });
          el.appendChild(b);
        });
        // Line break before coarse/fine controls
        const br = document.createElement("div");
        br.style.flexBasis = "100%";
        el.appendChild(br);
      }

      // 2. Coarse / fine step buttons
      const addStepBtn = (label, delta) => {
        const b = document.createElement("button");
        b.textContent = label;
        b.addEventListener("click", (ev) => {
          ev.stopPropagation();
          if (cmd.has_variable_step && typeof delta === "number") {
            execute(cmd.identifier, { action: "variable_step", value: delta });
          } else {
            execute(cmd.identifier, { action: delta > 0 ? "inc" : "dec" });
          }
        });
        el.appendChild(b);
      };

      if (max != null && max > POSITION_BUTTON_LIMIT && cmd.has_variable_step) {
        const coarse = Math.max(1, Math.round(max * 0.10));
        const fine   = Math.max(1, Math.round(max * 0.02));
        addStepBtn(`– ${coarse}  (-10 %)`, -coarse);
        addStepBtn(`+ ${coarse}  (+10 %)`,  coarse);
        addStepBtn(`– ${fine}   (-2 %)`,   -fine);
        addStepBtn(`+ ${fine}   (+2 %)`,    fine);
      } else {
        addStepBtn("– Decrease", -1);
        addStepBtn("+ Increase",  1);
      }

      const hint = document.createElement("div");
      hint.className = "submenu-hint";
      hint.textContent = max != null
        ? `Continuous control (0–${max}). Use presets for quick levels, ± for fine adjustment.`
        : "Continuous control. Tap to step.";
      el.appendChild(hint);
    }
    // String input
    if (cmd.has_set_string) {
      const input = document.createElement("input");
      input.type = "text";
      input.placeholder = "Enter value…";
      input.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") {
          ev.preventDefault();
          sendString(cmd, input.value);
        }
      });
      const send = document.createElement("button");
      send.textContent = "Send";
      send.addEventListener("click", (ev) => {
        ev.stopPropagation();
        sendString(cmd, input.value);
      });
      el.appendChild(input);
      el.appendChild(send);
    }
    // Close button
    const close = document.createElement("button");
    close.className = "danger";
    close.textContent = "Close";
    close.addEventListener("click", (ev) => {
      ev.stopPropagation();
      expandedId = null;
      renderResults();
    });
    el.appendChild(close);
    return el;
  }

  // ── Click handlers ─────────────────────────────────────────
  function onRowClick(ev, cmd, idx) {
    // Star hit-test — avoid expanding submenu when user taps the star
    const star = ev.target.closest(".star");
    if (star) {
      ev.stopPropagation();
      toggleFavorite(cmd.identifier);
      return;
    }
    selectedIdx = idx;

    // Keyboard shortcut — send immediately
    if (cmd.source === "keyboard") {
      if (cmd.key_combo) {
        execute(cmd.identifier);
      } else {
        toast("No key binding assigned", "err");
      }
      return;
    }

    // DCS-BIOS
    const isSimpleToggle =
      cmd.max_value != null && cmd.max_value <= 1
      && !cmd.is_momentary && !cmd.is_spring_loaded;
    const isSimpleMomentary =
      cmd.is_momentary && cmd.max_value != null && cmd.max_value <= 1;

    if (isSimpleToggle) {
      // Show optimistic feedback before the response lands
      flashRow(cmd.identifier, "…");
      execute(cmd.identifier, { action: "toggle" }).then((r) => {
        const label = toggleLabel(cmd, r && r.new);
        flashRow(cmd.identifier, label, "ok");
        toast(`${cmd.description}: ${label}`, "ok");
      }).catch((e) => {
        console.error(e);
        flashRow(cmd.identifier, "ERR", "err");
        toast("Toggle failed", "err");
      });
      return;
    }
    if (isSimpleMomentary) {
      // Press and release with a short hold so DCS registers it
      flashRow(cmd.identifier, "PRESSED", "ok");
      execute(cmd.identifier, { action: "momentary_press" })
        .then(() => new Promise((r) => setTimeout(r, 180)))
        .then(() => execute(cmd.identifier, { action: "momentary_release" }))
        .then(() => flashRow(cmd.identifier, "RELEASED"))
        .catch(() => flashRow(cmd.identifier, "ERR", "err"));
      return;
    }

    // Multi-position, stepper, or string input → expand submenu inline
    expandedId = (expandedId === cmd.identifier) ? null : cmd.identifier;
    renderResults();
  }

  async function onPositionClick(cmd, pos, btn) {
    try {
      await execute(cmd.identifier, { action: "set_state", value: pos });
      if (cmd.is_spring_loaded && pos !== 1) {
        btn.classList.add("holding");
        btn.textContent = btn.textContent + "  — HOLDING";
      } else if (cmd.is_spring_loaded && pos === 1) {
        // Released
        expandedId = null;
        renderResults();
        toast("Released to center", "ok");
      } else {
        // Non-spring-loaded selectors: collapse after picking
        expandedId = null;
        runSearch(searchInput.value);  // re-fetch to update any dynamic state
      }
    } catch (e) {
      console.error(e);
      toast("Execute failed", "err");
    }
  }

  async function sendString(cmd, value) {
    const v = (value || "").trim();
    if (!v) { toast("Enter a value first", "err"); return; }
    try {
      await execute(cmd.identifier, { action: "set_string", value: v });
      toast("Sent", "ok");
      expandedId = null;
      renderResults();
    } catch (e) {
      console.error(e);
      toast("Send failed", "err");
    }
  }

  async function toggleFavorite(identifier) {
    try {
      const r = await apiPost("/api/favorite", { identifier });
      // Update locally so re-render reflects the new state even before search
      const row = lastResults.find((c) => c.identifier === identifier);
      if (row) row.favorite = !!r.favorite;
      renderResults();
      // Re-run search to re-sort favorites to the top
      runSearch(searchInput.value);
    } catch (e) {
      console.error(e);
      toast("Favorite toggle failed", "err");
    }
  }

  async function execute(identifier, extra) {
    const body = Object.assign({ identifier }, extra || {});
    return apiPost("/api/execute", body);
  }

  // ── BIOS status polling ────────────────────────────────────
  async function refreshStatus() {
    try {
      const s = await apiGet("/api/status");
      biosDot.classList.toggle("dot-on", !!s.bios_connected);
      biosDot.classList.toggle("dot-off", !s.bios_connected);
      biosDot.title = s.bios_connected ? "DCS-BIOS connected" : "DCS-BIOS disconnected";
    } catch (e) {
      // Server might be busy or shutting down — silent
    }
  }

  // ── Virtual keyboard ──────────────────────────────────────
  // OpenKneeboard's WebView2 often doesn't forward physical keyboard input,
  // so we ship an on-screen QWERTY that works via the OpenKneeboard cursor.
  const kbdEl = document.getElementById("keyboard");
  const kbdToggle = document.getElementById("kbd-toggle");
  const clearBtn = document.getElementById("clear-btn");

  const KB_ROWS = [
    "1234567890".split(""),
    "qwertyuiop".split(""),
    "asdfghjkl".split(""),
    "zxcvbnm".split(""),
  ];

  function buildKeyboard() {
    kbdEl.innerHTML = "";
    KB_ROWS.forEach((row) => {
      const rowEl = document.createElement("div");
      rowEl.className = "kb-row";
      row.forEach((ch) => {
        const b = document.createElement("button");
        b.className = "kb-key";
        b.textContent = ch;
        b.addEventListener("click", (ev) => {
          ev.preventDefault();
          typeChar(ch);
        });
        rowEl.appendChild(b);
      });
      kbdEl.appendChild(rowEl);
    });
    // Bottom row: space + backspace
    const last = document.createElement("div");
    last.className = "kb-row";
    const space = document.createElement("button");
    space.className = "kb-key kb-wide";
    space.textContent = "Space";
    space.addEventListener("click", (ev) => {
      ev.preventDefault();
      typeChar(" ");
    });
    const back = document.createElement("button");
    back.className = "kb-key kb-wide kb-back";
    back.textContent = "⌫ Back";
    back.addEventListener("click", (ev) => {
      ev.preventDefault();
      backspace();
    });
    last.appendChild(space);
    last.appendChild(back);
    kbdEl.appendChild(last);
  }

  function typeChar(ch) {
    searchInput.value += ch;
    scheduleSearch();
  }
  function backspace() {
    searchInput.value = searchInput.value.slice(0, -1);
    scheduleSearch();
  }
  function clearSearch() {
    searchInput.value = "";
    scheduleSearch();
  }

  kbdToggle.addEventListener("click", (ev) => {
    ev.preventDefault();
    kbdEl.classList.toggle("hidden");
    kbdToggle.classList.toggle("active", !kbdEl.classList.contains("hidden"));
  });
  clearBtn.addEventListener("click", (ev) => {
    ev.preventDefault();
    clearSearch();
  });

  buildKeyboard();

  // ── Boot ──────────────────────────────────────────────────
  searchInput.addEventListener("input", scheduleSearch);
  runSearch("");        // prewarm with default results
  refreshStatus();
  setInterval(refreshStatus, 2000);
  // Re-focus the search box if the user clicks anywhere empty
  document.addEventListener("click", (ev) => {
    if (ev.target === document.body || ev.target === resultsEl) {
      searchInput.focus();
    }
  });
  searchInput.focus();
})();
