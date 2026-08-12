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
    row.dataset.severity = evt.severity ?? "";
    row.dataset.host = evt.host || "";
    row.dataset.program = evt.program || "";
    row.dataset.message = evt.message || "";

    const time = new Date(evt.received_at).toLocaleTimeString();
    row.innerHTML = `
      <span class="live-time">${time}</span>
      <span class="badge live-sev sev-${sevClass}">${sevClass}</span>
      <span class="live-host">${escapeHtml(evt.host || "-")}</span>
      <span class="live-program">${escapeHtml(evt.program || "-")}</span>
      <span class="live-message">${escapeHtml(evt.message || "")}</span>
      <span class="live-actions">
        <a class="btn btn-sm" href="/tickets/new?ticket_type=incident&source_event_id=${evt.id}">Incident</a>
        <a class="btn btn-sm" href="/tickets/new?ticket_type=vulnerability&source_event_id=${evt.id}">Vuln</a>
      </span>
    `;
    return row;
  }

  [filterText, filterSeverity].forEach((el) => {
    el.addEventListener("input", () => {
      feed.querySelectorAll(".live-row").forEach(applyFilterToRow);
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
      statusBadge.textContent = "disconnected -- retrying…";
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
