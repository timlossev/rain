// RAIN client-side glue -- deliberately dependency-free (no htmx/Alpine),
// this is the entire JS footprint of the app in Milestone 1.

document.addEventListener("DOMContentLoaded", () => {
  // Expand/collapse nav tree branches, persisted per-branch across visits.
  document.querySelectorAll("[data-nav-toggle]").forEach((btn) => {
    const item = btn.closest(".nav-item");
    const storeKey = "rain-nav-" + (item.dataset.navKey || btn.textContent.trim());
    if (localStorage.getItem(storeKey) === "1") item.classList.add("open");
    btn.addEventListener("click", (evt) => {
      evt.preventDefault();
      const isOpen = item.classList.toggle("open");
      localStorage.setItem(storeKey, isOpen ? "1" : "0");
    });
  });

  // Auto-open the branch containing the current page.
  const current = document.querySelector('.nav-link[href="' + location.pathname + location.search + '"]')
    || document.querySelector('.nav-link[href^="' + location.pathname + '"]');
  if (current) {
    let el = current.closest(".nav-item");
    while (el) {
      el.classList.add("open");
      el = el.parentElement ? el.parentElement.closest(".nav-item") : null;
    }
  }

  // List/create tab pairs (and any other same-page tab group).
  document.querySelectorAll("[data-tabs]").forEach((container) => {
    const buttons = container.querySelectorAll("[data-tab-btn]");
    const panels = container.querySelectorAll("[data-tab-panel]");
    buttons.forEach((btn) => {
      btn.addEventListener("click", () => {
        const target = btn.dataset.tabBtn;
        buttons.forEach((b) => b.classList.toggle("active", b === btn));
        panels.forEach((p) => p.classList.toggle("active", p.dataset.tabPanel === target));
      });
    });
  });

  // Confirm before any destructive form submit.
  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (evt) => {
      if (!window.confirm(form.dataset.confirm)) evt.preventDefault();
    });
  });

  // Single "Menu" button drives both behaviors, depending on viewport:
  // on narrow screens it opens/closes the off-canvas sidebar; on wide
  // screens it collapses the sidebar down to icons-only, persisted across
  // visits via localStorage.
  const sidebar = document.querySelector(".sidebar");
  const navBtn = document.querySelector("[data-nav-open]");
  const isMobile = () => window.matchMedia("(max-width: 860px)").matches;
  if (sidebar) {
    const COLLAPSE_KEY = "rain-sidebar-collapsed";
    if (!isMobile()) sidebar.classList.toggle("collapsed", localStorage.getItem(COLLAPSE_KEY) === "1");
    if (navBtn) {
      navBtn.addEventListener("click", () => {
        if (isMobile()) {
          document.body.classList.toggle("nav-open");
        } else {
          const collapsed = !sidebar.classList.contains("collapsed");
          sidebar.classList.toggle("collapsed", collapsed);
          localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0");
        }
      });
    }

    // Drag-to-resize, expanded state only. Width persisted across visits;
    // collapsed (icons-only) mode ignores it and falls back to its own
    // fixed width.
    const WIDTH_KEY = "rain-sidebar-width";
    const MIN_WIDTH = 200;
    const MAX_WIDTH = 440;
    const savedWidth = parseInt(localStorage.getItem(WIDTH_KEY) || "", 10);
    if (!isMobile() && savedWidth >= MIN_WIDTH && savedWidth <= MAX_WIDTH) {
      sidebar.style.setProperty("--sidebar-width", savedWidth + "px");
    }
    const handle = document.querySelector("[data-sidebar-resize]");
    if (handle) {
      handle.addEventListener("mousedown", (evt) => {
        if (isMobile() || sidebar.classList.contains("collapsed")) return;
        evt.preventDefault();
        sidebar.classList.add("resizing");
        handle.classList.add("active");
        const startX = evt.clientX;
        const startWidth = sidebar.getBoundingClientRect().width;
        const onMove = (moveEvt) => {
          const next = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, startWidth + (moveEvt.clientX - startX)));
          sidebar.style.setProperty("--sidebar-width", next + "px");
        };
        const onUp = () => {
          sidebar.classList.remove("resizing");
          handle.classList.remove("active");
          document.removeEventListener("mousemove", onMove);
          document.removeEventListener("mouseup", onUp);
          localStorage.setItem(WIDTH_KEY, Math.round(sidebar.getBoundingClientRect().width));
        };
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
      });
    }
  }

  // Asset form: reload the custom-field inputs when the asset type changes.
  const typeSelect = document.querySelector("[data-asset-type-select]");
  const fieldsContainer = document.querySelector("[data-fields-container]");
  if (typeSelect && fieldsContainer) {
    typeSelect.addEventListener("change", async () => {
      const resp = await fetch(`/assets/fields-for-type/${typeSelect.value}`);
      if (resp.ok) fieldsContainer.innerHTML = await resp.text();
    });
  }

  // Export column picker: keep the "order" input in sync with visual position.
  document.querySelectorAll("[data-export-columns]").forEach((table) => {
    table.querySelectorAll("input[type=checkbox]").forEach((cb, idx) => {
      const orderInput = table.querySelector(`input[name="order_${cb.value}"]`);
      if (orderInput && !orderInput.value) orderInput.value = String(idx);
    });
  });
});
