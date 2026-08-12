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

  // Confirm before any destructive form submit.
  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (evt) => {
      if (!window.confirm(form.dataset.confirm)) evt.preventDefault();
    });
  });

  // Mobile nav toggle.
  const navBtn = document.querySelector("[data-nav-open]");
  if (navBtn) navBtn.addEventListener("click", () => document.body.classList.toggle("nav-open"));

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
