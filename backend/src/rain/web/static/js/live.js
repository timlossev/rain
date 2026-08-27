// Live syslog viewer: connects to /tickets/live/ws, prepends rows to a
// capped scrolling feed, and filters client-side (text + severity
// threshold). Reconnects automatically on drop.
(() => {
  const feed = document.getElementById("live-feed");
  if (!feed) return;

  const statusBadge = document.getElementById("live-status");
  const pauseBtn = document.getElementById("live-pause");
  const filterText = document.getElementById("live-filter-text");
  const filterSeverity = document.getElementById("live-filter-severity");

  const MAX_ROWS = 300;
  let paused = false;

  pauseBtn.addEventListener("click", () => {
    paused = !paused;
    pauseBtn.textContent = paused ? "Resume" : "Pause";
  });

  function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  function matchesFilter(evt) {
    const text = filterText.value.trim().toLowerCase();
    if (text) {
      const haystack = `${evt.host || ""} ${evt.program || ""} ${evt.message || ""}`.toLowerCase();
      if (!haystack.includes(text)) return false;
    }
    const threshold = parseInt(filterSeverity.value, 10);
    if (evt.severity !== null && evt.severity !== undefined && evt.severity > threshold) return false;
    return true;
  }

  function rowDataset(row) {
    return {
      severity: row.dataset.severity === "" ? null : parseInt(row.dataset.severity, 10),
      host: row.dataset.host,
      program: row.dataset.program,
      message: row.dataset.message,
    };
  }

  function applyFilterToRow(row) {
    row.style.display = matchesFilter(rowDataset(row)) ? "" : "none";
  }

  function renderRow(evt) {
    const row = document.createElement("div");
    const sevClass = evt.severity_label || "unknown";
    row.className = `live-row sev-${sevClass}`;
    row.dataset.id = evt.id;
    row.dataset.severity = evt.severity ?? "";
    row.dataset.host = evt.host || "";
    row.dataset.program = evt.program || "";
    row.dataset.message = evt.message || "";
    row.title = "Click to view the full message";

    const time = new Date(evt.received_at).toLocaleTimeString();
    // event_format is "plain" for standard syslog text (the common
    // case) -- only CEF/JSON/kv-recognized bodies (see
    // rain.modules.tickets.event_formats) get a badge at all, so this
    // stays quiet for most events instead of labeling every row.
    const formatBadge =
      evt.event_format && evt.event_format !== "plain"
        ? `<span class="badge live-format" title="Message body recognized as ${escapeHtml(evt.event_format.toUpperCase())} and summarized">${escapeHtml(evt.event_format.toUpperCase())}</span>`
        : "";
    row.innerHTML = `
      <input type="checkbox" class="live-select" data-live-select aria-label="Select this event">
      <span class="live-time">${time}</span>
      <span class="badge live-sev sev-${sevClass}">${sevClass}</span>
      <span class="live-host">${escapeHtml(evt.host || "-")}</span>
      <span class="live-program">${escapeHtml(evt.program || "-")}</span>
      <span class="live-message">${formatBadge}${escapeHtml(evt.message || "")}</span>
    `;
    return row;
  }

  [filterText, filterSeverity].forEach((el) => {
    el.addEventListener("input", () => {
      feed.querySelectorAll(".live-row").forEach(applyFilterToRow);
    });
  });

  // Selection menu: the [...] dropdown in the panel-row acts on whichever
  // rows are currently checked, replacing the old per-row Incident/Vuln
  // links -- those only ever handled one event at a time.
  const selectionMenu = document.getElementById("live-selection-menu");
  const selectionCount = document.getElementById("live-selection-count");
  const promoteForm = document.getElementById("live-bulk-promote-form");
  const discardForm = document.getElementById("live-bulk-discard-form");

  function selectedRows() {
    return Array.from(feed.querySelectorAll("[data-live-select]:checked")).map((cb) => cb.closest(".live-row"));
  }

  function updateSelectionUI() {
    const count = selectedRows().length;
    selectionCount.textContent = `${count} selected`;
    selectionMenu.hidden = count === 0;
  }

  feed.addEventListener("change", (evt) => {
    if (evt.target.matches("[data-live-select]")) updateSelectionUI();
  });

  // Full-message modal: the WebSocket feed only ever carries message
  // truncated to 500 chars (live.py's _event_payload), never the full
  // text or raw/parsed_fields -- opening this always re-fetches the
  // complete row from the server. Reachable two ways: clicking a row
  // directly, or "View full message" in the [...] menu (acts on the
  // first checked row, same convention "Correlate" below already uses
  // for a value that only makes sense singular).
  const messageModal = document.getElementById("live-message-modal");
  const messageTitle = document.getElementById("live-message-title");
  const messageBody = document.getElementById("live-message-body");

  async function openFullMessage(row) {
    if (!messageModal || !row) return;
    const id = row.dataset.id;
    messageTitle.textContent = `${row.dataset.host || "-"} / ${row.dataset.program || "-"}`;
    messageBody.innerHTML = '<p class="muted">Loading...</p>';
    messageModal.hidden = false;
    try {
      // Both the success and 404 branches of the route already return
      // ready-to-show HTML (a detail fragment, or an inline "no longer
      // available" message) -- no need to branch on resp.ok here.
      const resp = await fetch(`/tickets/live/${id}/full`);
      messageBody.innerHTML = await resp.text();
    } catch (err) {
      messageBody.innerHTML = '<p class="muted">Couldn\'t load this event.</p>';
    }
  }

  feed.addEventListener("click", (evt) => {
    // Ignore the checkbox itself (selecting a row for a bulk action
    // shouldn't also pop the modal) and anything already inside a link.
    if (evt.target.closest("[data-live-select]")) return;
    const row = evt.target.closest(".live-row");
    if (row) openFullMessage(row);
  });

  document.querySelectorAll("[data-live-action]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const rows = selectedRows();
      if (!rows.length) return;
      const action = btn.dataset.liveAction;

      if (action === "view-full") {
        openFullMessage(rows[0]);
      } else if (action === "incident" || action === "vulnerability") {
        promoteForm.querySelector("[name=event_ids]").value = rows.map((row) => row.dataset.id).join(",");
        promoteForm.querySelector("[name=ticket_type]").value = action;
        promoteForm.submit();
      } else if (action === "discard") {
        const hosts = Array.from(new Set(rows.map((row) => row.dataset.host).filter(Boolean)));
        if (!hosts.length) return; // nothing with a host among the selection to build a rule from
        discardForm.dataset.confirm =
          `Add a discard rule for ${hosts.length} host(s) (${hosts.join(", ")})? ` +
          "Future events from them will be dropped before reaching any tenant - this doesn't delete what's already here.";
        discardForm.querySelector("[name=hosts]").value = hosts.join(",");
        discardForm.submit();
      } else if (action === "new-policy") {
        const params = new URLSearchParams({
          prefill_pattern: rows[0].dataset.message.slice(0, 200),
          prefill_match_field: "message",
        });
        window.location.href = `/tickets/rules/all?${params.toString()}`;
      }
    });
  });

  function connect() {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${scheme}://${location.host}/tickets/live/ws`);

    ws.onopen = () => {
      statusBadge.textContent = "live";
      statusBadge.classList.add("badge-accent");
    };
    ws.onclose = () => {
      statusBadge.textContent = "disconnected - retrying…";
      statusBadge.classList.remove("badge-accent");
      setTimeout(connect, 3000);
    };
    ws.onerror = () => ws.close();
    ws.onmessage = (msg) => {
      if (paused) return;
      const evt = JSON.parse(msg.data);
      const row = renderRow(evt);
      applyFilterToRow(row);
      feed.prepend(row);
      while (feed.children.length > MAX_ROWS) feed.removeChild(feed.lastChild);
    };
  }

  connect();
})();
