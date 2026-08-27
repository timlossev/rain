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
        // entry.path is the result's own immediate parent category label
        // (e.g. "Tenant Administration" for a leaf nested two levels
        // under "Admin" -- see the searchIndex map above) -- named after
        // that category directly, not this search box's own name, which
        // told the visitor nothing about where the result actually lives.
        path.textContent = entry.path ? `Option in ${entry.path}` : "Option";
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

  // Predictive user-search picker (ticket assignee fields) -- same
  // interaction shape as Quick Navigation above, but backed by a live
  // endpoint (data-user-picker-endpoint) since the full user list can't be
  // pre-rendered into the page the way the small nav tree is. Keeps a text
  // input (what's shown/typed) in sync with a hidden input (the real form
  // value, a user id) -- typing clears the hidden value until a result is
  // actually picked, so a half-typed search can't silently submit a stale id.
  document.querySelectorAll("[data-user-picker]").forEach((picker) => {
    const input = picker.querySelector("[data-user-picker-input]");
    const hidden = picker.querySelector("[data-user-picker-value]");
    const results = picker.querySelector("[data-user-picker-results]");
    const endpoint = picker.dataset.userPickerEndpoint;
    if (!input || !hidden || !results || !endpoint) return;

    let matches = [];
    let activeIndex = -1;
    let debounceTimer = null;

    const renderResults = () => {
      results.innerHTML = "";
      matches.forEach((entry, idx) => {
        const item = document.createElement("div");
        item.className = "user-picker-result" + (idx === activeIndex ? " active" : "");
        item.textContent = entry.label;
        item.addEventListener("mousedown", (evt) => {
          evt.preventDefault();
          select(entry);
        });
        results.appendChild(item);
      });
      results.hidden = matches.length === 0;
    };

    const select = (entry) => {
      hidden.value = entry.id;
      input.value = entry.label;
      matches = [];
      activeIndex = -1;
      results.hidden = true;
      // Opt-in (data-user-picker-auto-submit) -- a filter box (tickets
      // list's "Filter by asset") wants picking a suggestion to apply
      // immediately, unlike a data-entry form (ticket form's own asset
      // field) where picking is just one of several fields on the way to
      // an explicit Save.
      if (picker.dataset.userPickerAutoSubmit !== undefined) {
        const form = picker.closest("form");
        if (form) form.requestSubmit();
      }
    };

    input.addEventListener("input", () => {
      hidden.value = "";
      const q = input.value.trim();
      clearTimeout(debounceTimer);
      if (q.length < 2) {
        matches = [];
        renderResults();
        return;
      }
      debounceTimer = setTimeout(async () => {
        try {
          const resp = await fetch(`${endpoint}?q=${encodeURIComponent(q)}`);
          matches = resp.ok ? await resp.json() : [];
        } catch (err) {
          matches = [];
        }
        activeIndex = -1;
        renderResults();
      }, 200);
    });
    input.addEventListener("keydown", (evt) => {
      if (evt.key === "ArrowDown" && matches.length) {
        evt.preventDefault();
        activeIndex = Math.min(activeIndex + 1, matches.length - 1);
        renderResults();
      } else if (evt.key === "ArrowUp" && matches.length) {
        evt.preventDefault();
        activeIndex = Math.max(activeIndex - 1, 0);
        renderResults();
      } else if (evt.key === "Enter" && matches.length) {
        evt.preventDefault();
        select(matches[activeIndex] || matches[0]);
      } else if (evt.key === "Escape") {
        matches = [];
        renderResults();
      }
    });
    document.addEventListener("click", (evt) => {
      if (!picker.contains(evt.target)) results.hidden = true;
    });
  });

  // Assets list search: same live-dropdown shape as the user picker above,
  // but there's no hidden id field to fill in -- picking a suggestion
  // navigates straight to that asset's edit page (a "jump to" quick
  // search), while the input is *also* a real form field (name="q"), so
  // pressing Enter with nothing highlighted, or clicking Search, falls
  // through to a normal submit that filters the table server-side via the
  // same q= param (rain.modules.assets.service.asset_search_filter).
  document.querySelectorAll("[data-asset-search]").forEach((picker) => {
    const input = picker.querySelector("[data-asset-search-input]");
    const results = picker.querySelector("[data-asset-search-results]");
    const endpoint = picker.dataset.assetSearchEndpoint;
    if (!input || !results || !endpoint) return;

    let matches = [];
    let activeIndex = -1;
    let debounceTimer = null;

    const renderResults = () => {
      results.innerHTML = "";
      matches.forEach((entry, idx) => {
        const a = document.createElement("a");
        a.className = "asset-search-result" + (idx === activeIndex ? " active" : "");
        a.href = entry.href;
        a.textContent = entry.label;
        if (entry.sub) {
          const sub = document.createElement("span");
          sub.className = "asset-search-result-sub";
          sub.textContent = entry.sub;
          a.appendChild(sub);
        }
        results.appendChild(a);
      });
      results.hidden = matches.length === 0;
    };

    input.addEventListener("input", () => {
      const q = input.value.trim();
      clearTimeout(debounceTimer);
      if (q.length < 2) {
        matches = [];
        activeIndex = -1;
        renderResults();
        return;
      }
      debounceTimer = setTimeout(async () => {
        try {
          const resp = await fetch(`${endpoint}?q=${encodeURIComponent(q)}`);
          matches = resp.ok ? await resp.json() : [];
        } catch (err) {
          matches = [];
        }
        activeIndex = -1;
        renderResults();
      }, 200);
    });
    input.addEventListener("keydown", (evt) => {
      if (evt.key === "ArrowDown" && matches.length) {
        evt.preventDefault();
        activeIndex = Math.min(activeIndex + 1, matches.length - 1);
        renderResults();
      } else if (evt.key === "ArrowUp" && matches.length) {
        evt.preventDefault();
        activeIndex = Math.max(activeIndex - 1, 0);
        renderResults();
      } else if (evt.key === "Enter" && activeIndex >= 0 && matches[activeIndex]) {
        // Only hijack Enter when a suggestion is actually highlighted --
        // otherwise let the surrounding <form> submit normally (filters
        // the table via q=, same as clicking Search).
        evt.preventDefault();
        window.location.href = matches[activeIndex].href;
      } else if (evt.key === "Escape") {
        matches = [];
        activeIndex = -1;
        renderResults();
      }
    });
    document.addEventListener("click", (evt) => {
      if (!picker.contains(evt.target)) results.hidden = true;
    });
  });

  // List/create tab pairs (and any other same-page tab group). A [data-tabs]
  // group can nest inside another one (documents/detail.html: the page's
  // own Description/Contents/Auto-update/Links tabs, with a second Write/
  // Preview tab group nested inside the Contents panel for markdown) --
  // container.querySelectorAll() finds descendants at any depth, so
  // without the closest() filter below, the outer group's button/panel
  // lists would also pick up the inner group's buttons/panels (and vice
  // versa). Clicking either group's button would then also fire the
  // other's now-mismatched toggle, deactivating a panel that has nothing
  // to do with the button just clicked (confirmed live: clicking the
  // outer "Contents" tab deactivated the inner "Write" panel as a side
  // effect, since it was included in the outer group's panels list too).
  document.querySelectorAll("[data-tabs]").forEach((container) => {
    const ownButtons = Array.from(container.querySelectorAll("[data-tab-btn]")).filter(
      (el) => el.closest("[data-tabs]") === container
    );
    const ownPanels = Array.from(container.querySelectorAll("[data-tab-panel]")).filter(
      (el) => el.closest("[data-tabs]") === container
    );
    ownButtons.forEach((btn) => {
      btn.addEventListener("click", () => {
        const target = btn.dataset.tabBtn;
        ownButtons.forEach((b) => b.classList.toggle("active", b === btn));
        ownPanels.forEach((p) => p.classList.toggle("active", p.dataset.tabPanel === target));
        // The portal's mobile burger nav re-purposes this same tab-
        // buttons row as a [data-menu-panel] (see report.html) --
        // picking an item there should close the dropdown behind it
        // like a normal mobile nav, not leave it open over the panel
        // that just switched. A no-op everywhere else this tab
        // plumbing is used, since none of those buttons live inside a
        // [data-menu-panel].
        const menuPanel = btn.closest("[data-menu-panel]");
        if (menuPanel) {
          menuPanel.hidden = true;
          menuPanel.closest("[data-menu]")?.querySelector("[data-menu-toggle]")?.setAttribute("aria-expanded", "false");
        }
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

  // Linked-document title click -> preview modal, for every linked document
  // (clicking a document is meant for reading, not navigation -- the pencil
  // icon next to it is the way to actually open/edit the full document).
  // For inline-viewable (txt/md) documents this renders the same body-preview
  // fragment the inline editor's Preview tab uses; the server 400s for any
  // other file type (no renderer for it), so this falls back to opening the
  // raw file in a new tab, letting the browser's own PDF/image viewer show it.
  const previewModal = document.querySelector("#doc-preview-modal");
  const previewBody = document.querySelector("#doc-preview-body");
  const previewTitle = document.querySelector("#doc-preview-title");
  document.querySelectorAll("[data-doc-preview]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const docId = btn.dataset.docPreview;
      if (!previewModal) return;
      previewTitle.textContent = btn.dataset.docTitle || "";
      previewBody.innerHTML = "<p class=\"muted\">Loading...</p>";
      previewModal.hidden = false;
      try {
        const resp = await fetch(`/documents/${docId}/body-preview`);
        if (resp.status === 400) {
          previewModal.hidden = true;
          window.open(`/documents/${docId}/download`, "_blank");
          return;
        }
        previewBody.innerHTML = resp.ok ? await resp.text() : "<p class=\"muted\">Couldn't load preview.</p>";
      } catch (err) {
        previewBody.innerHTML = "<p class=\"muted\">Couldn't load preview.</p>";
      }
    });
  });
  // Client portal: ticket number click -> lightweight timeline modal
  // (rain.modules.portal.router.portal_ticket_timeline), same fetch-and-
  // inject shape as the doc-preview modal just above. The modal title
  // bar is set synchronously from the link's own text (the ticket
  // number) rather than waiting on the fetch, so it appears instantly;
  // the fragment itself (title, severity/status, the timeline, "Edit
  // ticket") comes from the response. Re-activates the fetched
  // fragment's own Newest/Oldest-first toggle every time (window.RAIN.
  // activateActivitySortToggle, defined below) since that markup didn't
  // exist at page load for the page-load-time binding to have found.
  const timelineModal = document.querySelector("#ticket-timeline-modal");
  const timelineBody = document.querySelector("#ticket-timeline-body");
  const timelineTitle = document.querySelector("#ticket-timeline-title");
  document.querySelectorAll("[data-ticket-timeline]").forEach((link) => {
    link.addEventListener("click", async (evt) => {
      if (!timelineModal) return;
      evt.preventDefault();
      const ticketRef = link.dataset.ticketTimeline;
      timelineTitle.textContent = ticketRef;
      timelineBody.innerHTML = "<p class=\"muted\">Loading...</p>";
      timelineModal.hidden = false;
      try {
        // location.pathname is this same portal page's own /portal/<slug>
        // -- appending /tickets/<ref> is portal_ticket_timeline's route,
        // as distinct from link.href (the /tickets/<ref> full-page
        // fallback this same click just preventDefault()-ed away from).
        const resp = await fetch(`${location.pathname.replace(/\/$/, "")}/tickets/${ticketRef}`);
        timelineBody.innerHTML = resp.ok ? await resp.text() : "<p class=\"muted\">Couldn't load this ticket.</p>";
        if (resp.ok && window.RAIN && window.RAIN.activateActivitySortToggle) {
          window.RAIN.activateActivitySortToggle(timelineBody);
        }
      } catch (err) {
        timelineBody.innerHTML = "<p class=\"muted\">Couldn't load this ticket.</p>";
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

  // Generic click-toggle dropdown: a trigger button ([data-menu-toggle])
  // opens an absolutely-positioned panel ([data-menu-panel]) inside a
  // [data-menu] wrapper. Click-toggle + click-outside/Escape-to-close
  // rather than hover -- shared by the topbar user-menu (name/role/Sign
  // out, which holds an actionable button hover would fumble) and each
  // tickets-list row's [...] quick-action menu, so this logic lives in
  // exactly one place instead of being duplicated per menu.
  document.querySelectorAll("[data-menu]").forEach((menu) => {
    const btn = menu.querySelector("[data-menu-toggle]");
    const panel = menu.querySelector("[data-menu-panel]");
    if (!btn || !panel) return;
    btn.addEventListener("click", (evt) => {
      evt.stopPropagation();
      const opening = panel.hidden;
      // Close any other open menu first -- otherwise a row menu left open
      // while another one (or the user menu) opens would stack up.
      document.querySelectorAll("[data-menu-panel]:not([hidden])").forEach((openPanel) => {
        if (openPanel === panel) return;
        openPanel.hidden = true;
        openPanel.closest("[data-menu]")?.querySelector("[data-menu-toggle]")?.setAttribute("aria-expanded", "false");
      });
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

  // Generic "Show more" for a long clamped text block (ticket detail's
  // own description -- see .ticket-description.clamped in app.css --
  // the first user of this, but opt-in via [data-clamp] rather than
  // hardcoded to that one element in case another long-text field wants
  // the same treatment later). The toggle button only ever appears when
  // the text is actually being clipped: scrollHeight only exceeds
  // clientHeight while -webkit-line-clamp (or any other overflow:
  // hidden clamp) is genuinely hiding content, so a description short
  // enough to fit within the clamp never grows a button with nothing to
  // expand. The +1 is slack for sub-pixel rounding, not a real
  // threshold -- without it a description landing exactly on the clamp
  // boundary could show a "Show more" that expands to reveal nothing.
  document.querySelectorAll("[data-clamp]").forEach((wrap) => {
    const target = wrap.querySelector("[data-clamp-target]");
    const toggle = wrap.querySelector("[data-clamp-toggle]");
    if (!target || !toggle) return;
    if (target.scrollHeight > target.clientHeight + 1) {
      toggle.hidden = false;
      toggle.addEventListener("click", () => {
        const stillClamped = target.classList.toggle("clamped");
        toggle.textContent = stillClamped ? "Show more" : "Show less";
      });
    }
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

  // New-ticket form: the start/end date + approval flow fields only make
  // sense for a change, so keep them hidden until Type = change is picked.
  const ticketTypeSelect = document.querySelector("#ticket_type");
  const changeFields = document.querySelector("[data-change-fields]");
  if (ticketTypeSelect && changeFields) {
    const syncChangeFields = () => { changeFields.hidden = ticketTypeSelect.value !== "change"; };
    ticketTypeSelect.addEventListener("change", syncChangeFields);
    syncChangeFields();
  }

  // Type-driven conditional fields (Platform Response Rule "Add action"
  // form, syslog source rules, notification channels -- a notification
  // channel for Slack/email, a URL+payload for a webhook, ...) -- each
  // group opts in via data-action-fields="type1,type2". Scoped per
  // select's own <form> (querySelectorAll + closest("form"), not a
  // single document-wide querySelector) so multiple independent
  // instances on the same page -- Notification Channels' "New channel"
  // modal plus one "Edit channel" modal per existing row -- each sync
  // only their own fields instead of the first select on the page
  // driving every group on the page (same class of scoping bug as the
  // nested-tabs one fixed above).
  document.querySelectorAll("[data-action-type-select]").forEach((select) => {
    const scope = select.closest("form") || document;
    const groups = scope.querySelectorAll("[data-action-fields]");
    if (!groups.length) return;
    const syncActionFields = () => {
      groups.forEach((group) => {
        const types = group.dataset.actionFields.split(",");
        group.hidden = !types.includes(select.value);
      });
    };
    select.addEventListener("change", syncActionFields);
    syncActionFields();
  });

  // Same [data-action-fields] convention as above, but driven by a
  // pill-styled radio group instead of a <select> (document detail's
  // "Link to" -- ticket/asset -- reads better as two pills than a
  // one-item dropdown). Scoped per group's own <form> for the same
  // multiple-instances reason as data-action-type-select.
  document.querySelectorAll("[data-pill-select]").forEach((group) => {
    const radios = group.querySelectorAll("input[type=radio]");
    const scope = group.closest("form") || document;
    const fieldGroups = scope.querySelectorAll("[data-action-fields]");
    if (!radios.length || !fieldGroups.length) return;
    const syncPillFields = () => {
      const checked = group.querySelector("input[type=radio]:checked");
      const value = checked ? checked.value : "";
      fieldGroups.forEach((fg) => {
        const types = fg.dataset.actionFields.split(",");
        fg.hidden = !types.includes(value);
      });
    };
    radios.forEach((radio) => radio.addEventListener("change", syncPillFields));
    syncPillFields();
  });

  // Click-to-edit field (ticket title, priority, ...): click the pencil
  // to swap a plain-text/badge display for an edit form (name/value
  // already rendered server-side either way, so this is a pure
  // show/hide -- no fetch needed) -- an always-visible input/select read
  // as excessive chrome for a field that's rarely edited.
  document.querySelectorAll("[data-inline-edit]").forEach((wrapper) => {
    const display = wrapper.querySelector("[data-inline-edit-display]");
    const toggleBtn = wrapper.querySelector("[data-inline-edit-toggle]");
    const form = wrapper.querySelector("[data-inline-edit-form]");
    const cancelBtn = wrapper.querySelector("[data-inline-edit-cancel]");
    if (!display || !toggleBtn || !form) return;
    const field = form.querySelector("input[type=text], select");

    toggleBtn.addEventListener("click", () => {
      display.hidden = true;
      form.hidden = false;
      if (field) {
        field.focus();
        if (field.select) field.select();
      }
    });
    if (cancelBtn) {
      cancelBtn.addEventListener("click", () => {
        form.reset(); // restores the input's value / select's selected option alike
        form.hidden = true;
        display.hidden = false;
      });
    }
  });

  // Activity feed / timeline: Newest first / Oldest first re-sorts the
  // already-rendered entries client-side (server always emits them
  // oldest-first, for the PDF export's chronological narrative -- this
  // just reorders the DOM, no re-fetch) by each entry's data-at
  // timestamp. Actually moves the elements (not a CSS flex-direction
  // flip) so a last-entry-specific border/connector CSS rule keeps
  // matching the true last item regardless of sort direction. Defaults
  // to newest-first on load, matching the pre-selected button.
  //
  // A named, re-runnable function (not just a page-load querySelectorAll
  // loop) because the client portal's ticket timeline modal
  // (window.RAIN.activateActivitySortToggle below) injects its own
  // fresh copy of this exact markup via fetch *after* page load, where
  // it wouldn't otherwise be found -- same reason [data-catalog-preview-
  // btn] above is a plain per-click handler instead of only running once.
  // `root` scopes the lookup (document by default, or just the newly-
  // injected fragment, so re-activating after a second fetch into the
  // same modal doesn't double-bind the first fragment's already-removed
  // buttons).
  const activateActivitySortToggle = (root) => {
    (root || document).querySelectorAll("[data-activity-sort-toggle]").forEach((toggle) => {
      // [data-activity-scope] (not .card) -- the ticket detail page's own
      // Activity card carries both this attribute and .card, but the
      // portal timeline modal's body isn't styled as a card at all, just
      // scoped with the same attribute so this lookup works identically
      // in either context.
      const scope = toggle.closest("[data-activity-scope]");
      const list = scope && scope.querySelector("[data-activity-list]");
      const buttons = toggle.querySelectorAll("[data-activity-sort]");
      if (!list || !buttons.length) return;

      const applySort = (direction) => {
        const entries = Array.from(list.querySelectorAll("[data-at]"));
        entries.sort((a, b) => {
          const cmp = (a.dataset.at || "").localeCompare(b.dataset.at || "");
          return direction === "desc" ? -cmp : cmp;
        });
        entries.forEach((el) => list.appendChild(el));
      };

      buttons.forEach((btn) => {
        btn.addEventListener("click", () => {
          buttons.forEach((b) => b.classList.remove("active"));
          btn.classList.add("active");
          applySort(btn.dataset.activitySort);
        });
      });

      applySort("desc");
    });
  };
  activateActivitySortToggle();
  window.RAIN = window.RAIN || {};
  window.RAIN.activateActivitySortToggle = activateActivitySortToggle;

  // Export column picker: keep the "order" input in sync with visual position.
  document.querySelectorAll("[data-export-columns]").forEach((table) => {
    table.querySelectorAll("input[type=checkbox]").forEach((cb, idx) => {
      const orderInput = table.querySelector(`input[name="order_${cb.value}"]`);
      if (orderInput && !orderInput.value) orderInput.value = String(idx);
    });
  });

  // Approval Flow step builder: the server pre-renders data-step-max rows
  // (blank ones are skipped on submit -- see admin.router's
  // _replace_approval_steps), this just shows/hides them so it reads as
  // an add/remove list instead of a fixed wall of empty rows. Removing a
  // row clears its inputs too, so a hidden-but-still-filled-in row can't
  // sneak a step back in on submit.
  document.querySelectorAll("[data-step-field]").forEach((field) => {
    const min = parseInt(field.dataset.stepMin, 10) || 1;
    const rows = Array.from(field.querySelectorAll("[data-step-row]"));
    const addBtn = field.querySelector("[data-add-step-btn]");
    if (!rows.length || !addBtn) return;

    const refresh = () => {
      const visible = rows.filter((row) => !row.hidden);
      addBtn.hidden = visible.length >= rows.length;
      visible.forEach((row) => {
        const removeBtn = row.querySelector("[data-remove-step-btn]");
        if (removeBtn) removeBtn.hidden = visible.length <= min;
      });
    };
    const clearRow = (row) => {
      // input[type=checkbox] and textarea: added for Service Catalog's
      // question rows (is_required, source_expression) -- harmless for
      // Approval Flow's own steps too, which have neither. Not load-
      // bearing either way: a removed row's field_key (type=text, always
      // cleared) is what actually makes the server skip it on submit
      // (see admin.router._replace_approval_steps and rain.modules.
      // catalog.service.replace_catalog_fields), this is just tidiness so
      // a re-added row doesn't resurface stale leftovers.
      row.querySelectorAll("input[type=text], input[type=hidden], textarea").forEach((el) => { el.value = ""; });
      row.querySelectorAll("select").forEach((el) => { el.value = ""; });
      row.querySelectorAll("input[type=checkbox]").forEach((el) => { el.checked = false; });
      const previewTarget = row.querySelector("[data-catalog-preview-target]");
      if (previewTarget) previewTarget.innerHTML = "";
    };

    addBtn.addEventListener("click", () => {
      const nextRow = rows.find((row) => row.hidden);
      if (nextRow) nextRow.hidden = false;
      refresh();
    });
    rows.forEach((row) => {
      const removeBtn = row.querySelector("[data-remove-step-btn]");
      if (!removeBtn) return;
      removeBtn.addEventListener("click", () => {
        clearRow(row);
        row.hidden = true;
        refresh();
      });
    });
    refresh();
  });

  // Service Catalog question builder's "Preview" button -- same fetch ->
  // inject-fragment shape as the Markdown body editor's Preview tab
  // above, just scoped to one [data-catalog-field-row] instead of a
  // whole document. Resolves against the live document with nothing
  // saved yet (rain.modules.admin.router.catalog_field_preview), so an
  // admin can check a regex/JSONPath before committing to it.
  document.querySelectorAll("[data-catalog-preview-btn]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest("[data-catalog-field-row]");
      const target = row && row.querySelector("[data-catalog-preview-target]");
      if (!row || !target) return;
      const docIdInput = row.querySelector("[data-user-picker-value]");
      const modeSelect = row.querySelector("[data-catalog-source-mode]");
      const exprInput = row.querySelector("[data-catalog-source-expression]");
      const typeSelect = row.querySelector("[data-catalog-field-type]");
      target.innerHTML = "<p class=\"muted\">Checking...</p>";
      try {
        const body = new URLSearchParams({
          source_document_id: (docIdInput && docIdInput.value) || "",
          source_mode: (modeSelect && modeSelect.value) || "",
          source_expression: (exprInput && exprInput.value) || "",
          field_type: (typeSelect && typeSelect.value) || "text",
        });
        const resp = await fetch("/admin/catalog/fields/preview", {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: body.toString(),
        });
        target.innerHTML = resp.ok ? await resp.text() : "<p class=\"muted\">Preview failed.</p>";
      } catch (err) {
        target.innerHTML = "<p class=\"muted\">Preview failed.</p>";
      }
    });
  });

  // Row checkbox multi-select for a bulk action bar -- first user is the
  // tickets list's "Mass close", generic enough (reads/writes nothing
  // ticket-specific) for any other [data-bulk-select] table later. The
  // header checkbox (data-bulk-select-all) toggles every row; any row
  // checkbox changing recomputes the count, shows/hides the bar, and
  // refills the hidden ids field on the action form (found via the ids
  // input's own closest("form") -- declared outside the table, since a
  // <form> can't itself contain another <table>'s action buttons the way
  // this page's layout wants -- rather than a hardcoded form id, so this
  // stays reusable for a differently-named bulk action later). The
  // confirm prompt's verb comes from data-bulk-select-verb on the bar
  // (e.g. "closed") rather than being hardcoded to one action's wording.
  document.querySelectorAll("[data-bulk-select]").forEach((table) => {
    const selectAll = table.querySelector("[data-bulk-select-all]");
    const bar = document.querySelector("[data-bulk-select-bar]");
    const countEl = bar && bar.querySelector("[data-bulk-select-count]");
    const idsInput = document.querySelector("[data-bulk-select-ids]");
    const actionForm = idsInput && idsInput.closest("form");
    const verb = (bar && bar.dataset.bulkSelectVerb) || "updated";

    const rows = () => Array.from(table.querySelectorAll("[data-bulk-select-row]"));

    const update = () => {
      const checked = rows().filter((cb) => cb.checked);
      if (bar) bar.hidden = checked.length === 0;
      if (countEl) countEl.textContent = `${checked.length} selected`;
      if (idsInput) idsInput.value = checked.map((cb) => cb.value).join(",");
      if (actionForm) {
        actionForm.dataset.confirm = `Mark ${checked.length} selected ticket(s) ${verb}?`;
      }
      if (selectAll) {
        selectAll.checked = checked.length > 0 && checked.length === rows().length;
        selectAll.indeterminate = checked.length > 0 && checked.length < rows().length;
      }
    };

    if (selectAll) {
      selectAll.addEventListener("change", () => {
        rows().forEach((cb) => { cb.checked = selectAll.checked; });
        update();
      });
    }
    table.addEventListener("change", (evt) => {
      if (evt.target.matches("[data-bulk-select-row]")) update();
    });
  });
});
