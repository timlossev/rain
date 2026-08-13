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

  // Nav search: typeahead over the already-rendered nav tree -- reads the
  // sidebar's own DOM as its index rather than hitting a search endpoint,
  // so it automatically only ever finds pages this user's role/tenant
  // context actually rendered a link for.
  const navSearchInput = document.querySelector("#nav-search-input");
  const navSearchResults = document.querySelector("#nav-search-results");
  if (navSearchInput && navSearchResults) {
    const searchIndex = Array.from(document.querySelectorAll(".nav-tree .nav-link"))
      .map((link) => {
        const item = link.closest(".nav-item");
        const parentItem = item && item.parentElement ? item.parentElement.closest(".nav-item") : null;
        const parentLabel = parentItem ? parentItem.querySelector(":scope > .nav-toggle .nav-label") : null;
        return {
          label: (link.querySelector(".nav-label") || link).textContent.trim(),
          path: parentLabel ? parentLabel.textContent.trim() : "",
          href: link.getAttribute("href"),
        };
      })
      .filter((entry) => entry.label && entry.href);

    let activeIndex = -1;

    const currentMatches = () => {
      const q = navSearchInput.value.trim().toLowerCase();
      if (!q) return [];
      return searchIndex.filter((entry) => entry.label.toLowerCase().includes(q)).slice(0, 8);
    };

    const renderResults = (matches) => {
      navSearchResults.innerHTML = "";
      matches.forEach((entry, idx) => {
        const a = document.createElement("a");
        a.className = "nav-search-result" + (idx === activeIndex ? " active" : "");
        a.href = entry.href;
        a.textContent = entry.label;
        const path = document.createElement("span");
        path.className = "nav-search-path";
        path.textContent = entry.path ? `Option in Quick Navigation (${entry.path})` : "Option in Quick Navigation";
        a.appendChild(path);
        navSearchResults.appendChild(a);
      });
      navSearchResults.hidden = matches.length === 0;
    };

    navSearchInput.addEventListener("input", () => {
      activeIndex = -1;
      renderResults(currentMatches());
    });
    navSearchInput.addEventListener("focus", () => {
      if (navSearchInput.value.trim()) renderResults(currentMatches());
    });
    navSearchInput.addEventListener("keydown", (evt) => {
      const matches = currentMatches();
      if (evt.key === "ArrowDown" && matches.length) {
        evt.preventDefault();
        activeIndex = Math.min(activeIndex + 1, matches.length - 1);
        renderResults(matches);
      } else if (evt.key === "ArrowUp" && matches.length) {
        evt.preventDefault();
        activeIndex = Math.max(activeIndex - 1, 0);
        renderResults(matches);
      } else if (evt.key === "Enter") {
        const target = matches[activeIndex] || matches[0];
        if (target) {
          evt.preventDefault();
          window.location.href = target.href;
        }
      } else if (evt.key === "Escape") {
        navSearchInput.value = "";
        navSearchResults.hidden = true;
      }
    });
    document.addEventListener("click", (evt) => {
      if (!navSearchInput.contains(evt.target) && !navSearchResults.contains(evt.target)) {
        navSearchResults.hidden = true;
      }
    });
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
