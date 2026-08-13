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

  // Markdown document body editor: "Preview" tab fetches a server-rendered
  // preview of the current textarea content (rain.modules.documents.
  // textbody.render_markdown -- the exact same renderer used for "Export
  // to PDF", so what's previewed here is what actually ships) rather than
  // reimplementing a Markdown parser in JS.
  document.querySelectorAll("[data-md-preview-tab]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const form = btn.closest("[data-md-editor]");
      const source = form && form.querySelector("[data-md-source]");
      const target = form && form.querySelector("[data-md-preview-target]");
      if (!source || !target) return;
      target.innerHTML = "<p class=\"muted\">Rendering...</p>";
      try {
        const resp = await fetch(form.action.replace(/\/body$/, "/preview-markdown"), {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: "body=" + encodeURIComponent(source.value),
        });
        target.innerHTML = resp.ok ? await resp.text() : "<p class=\"muted\">Preview failed.</p>";
      } catch (err) {
        target.innerHTML = "<p class=\"muted\">Preview failed.</p>";
      }
    });
  });

  // Linked-document "View" modal, for inline-viewable (txt/md) documents
  // only -- decided client-side off the filename extension so the
  // Linked Documents fragment (shared by ticket/asset detail) doesn't
  // need a server-side body_kind lookup per link. Fetches the same
  // rendered-body fragment the inline editor's Preview tab uses.
  const TEXT_PREVIEW_EXTENSIONS = [".txt", ".text", ".log", ".md", ".markdown"];
  const previewModal = document.querySelector("#doc-preview-modal");
  const previewBody = document.querySelector("#doc-preview-body");
  const previewTitle = document.querySelector("#doc-preview-title");
  document.querySelectorAll("[data-doc-preview]").forEach((btn) => {
    const filename = (btn.dataset.docFilename || "").toLowerCase();
    if (!TEXT_PREVIEW_EXTENSIONS.some((ext) => filename.endsWith(ext))) return;
    btn.hidden = false;
    btn.addEventListener("click", async () => {
      if (!previewModal) return;
      previewTitle.textContent = btn.dataset.docTitle || "";
      previewBody.innerHTML = "<p class=\"muted\">Loading...</p>";
      previewModal.hidden = false;
      try {
        const resp = await fetch(`/documents/${btn.dataset.docPreview}/body-preview`);
        previewBody.innerHTML = resp.ok ? await resp.text() : "<p class=\"muted\">Couldn't load preview.</p>";
      } catch (err) {
        previewBody.innerHTML = "<p class=\"muted\">Couldn't load preview.</p>";
      }
    });
  });
  // Generic modal plumbing -- shared by the doc-preview modal above and by
  // every "+ New X" button + modal (see _modal.html) that replaced the old
  // "New X" tabs sitewide: tabs are for switching between views of the same
  // data, a create-form belongs in a modal. A trigger just needs
  // data-modal-open="<modal id>"; the modal itself opts in with data-modal
  // so Escape/backdrop-click close it without every page wiring that up.
  document.querySelectorAll("[data-modal-open]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const modal = document.getElementById(btn.dataset.modalOpen);
      if (modal) modal.hidden = false;
    });
  });
  document.querySelectorAll(".modal-overlay[data-modal]").forEach((modal) => {
    modal.addEventListener("click", (evt) => {
      if (evt.target === modal || evt.target.closest("[data-modal-close]")) modal.hidden = true;
    });
  });
  document.addEventListener("keydown", (evt) => {
    if (evt.key !== "Escape") return;
    document.querySelectorAll(".modal-overlay[data-modal]:not([hidden])").forEach((modal) => { modal.hidden = true; });
  });

  // Topbar user-menu: icon button toggles a dropdown (name/role/Sign out).
  // Click-toggle + click-outside-to-close rather than hover -- it holds an
  // actionable Sign out button, and a hover-only menu is a bad fit for that.
  document.querySelectorAll("[data-user-menu]").forEach((menu) => {
    const btn = menu.querySelector("[data-user-menu-toggle]");
    const panel = menu.querySelector("[data-user-menu-panel]");
    if (!btn || !panel) return;
    btn.addEventListener("click", (evt) => {
      evt.stopPropagation();
      const opening = panel.hidden;
      panel.hidden = !opening;
      btn.setAttribute("aria-expanded", String(opening));
    });
    document.addEventListener("click", (evt) => {
      if (!panel.hidden && !menu.contains(evt.target)) {
        panel.hidden = true;
        btn.setAttribute("aria-expanded", "false");
      }
    });
    document.addEventListener("keydown", (evt) => {
      if (evt.key === "Escape" && !panel.hidden) {
        panel.hidden = true;
        btn.setAttribute("aria-expanded", "false");
      }
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
