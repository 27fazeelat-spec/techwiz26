// SkillSprint UI behaviour. Every feature degrades gracefully: without JS the pages still work.

// Theme toggle: light <-> dark. Starts from the stored choice, else the OS preference.
(function () {
  var button = document.querySelector("[data-theme-toggle]");
  if (!button) return;
  var root = document.documentElement;
  function current() {
    return root.dataset.theme || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  }
  function label() {
    var next = current() === "dark" ? "light" : "dark";
    button.setAttribute("aria-label", "Switch to " + next + " theme");
    button.title = "Switch to " + next + " theme";
  }
  label();
  button.addEventListener("click", function () {
    var next = current() === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    try { localStorage.setItem("skillsprint-theme", next); } catch (e) {}
    label();
  });
})();

// Mobile navigation drawer.
(function () {
  var open = document.querySelector("[data-nav-open]");
  var scrim = document.querySelector("[data-nav-close]");
  if (!open || !scrim) return;
  function set(state) {
    document.body.classList.toggle("nav-open", state);
    scrim.hidden = !state;
    open.setAttribute("aria-expanded", String(state));
  }
  open.addEventListener("click", function () { set(true); });
  scrim.addEventListener("click", function () { set(false); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") set(false); });
})();

// "/" focuses the search box, unless the user is typing somewhere.
document.addEventListener("keydown", function (e) {
  if (e.key !== "/" || /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) return;
  var box = document.querySelector(".topsearch input");
  if (box) { e.preventDefault(); box.focus(); }
});

// Dismissible flash messages.
document.querySelectorAll("[data-dismiss]").forEach(function (b) {
  b.addEventListener("click", function () {
    var flash = b.closest(".flash");
    flash.classList.add("is-leaving");
    setTimeout(function () { flash.remove(); }, 180);
  });
});

// Client-side filters: a [data-filter-group] of buttons with data-filter="value" hides
// [data-filter-item] elements inside [data-filter-scope] whose data-filter-value doesn't match.
document.querySelectorAll("[data-filter-group]").forEach(function (group) {
  var scope = document.querySelector(group.dataset.filterGroup);
  if (!scope) return;
  group.addEventListener("click", function (e) {
    var b = e.target.closest("[data-filter]");
    if (!b) return;
    group.querySelectorAll("[data-filter]").forEach(function (x) {
      x.classList.toggle("is-on", x === b);
      x.setAttribute("aria-pressed", String(x === b));
    });
    var v = b.dataset.filter;
    scope.querySelectorAll("[data-filter-item]").forEach(function (item) {
      var values = (item.dataset.filterValue || "").split(" ");
      item.classList.toggle("is-hidden", v !== "all" && values.indexOf(v) === -1);
    });
  });
});

// Client-side text search over rows: <input data-search="#scope"> matches [data-filter-item] text.
document.querySelectorAll("[data-search]").forEach(function (input) {
  var scope = document.querySelector(input.dataset.search);
  if (!scope) return;
  var counter = document.querySelector(input.dataset.searchCount || "none");
  input.addEventListener("input", function () {
    var q = input.value.trim().toLowerCase();
    var shown = 0;
    scope.querySelectorAll("[data-filter-item]").forEach(function (row) {
      var hit = !q || row.textContent.toLowerCase().indexOf(q) !== -1;
      row.classList.toggle("is-hidden", !hit);
      if (hit) shown++;
    });
    if (counter) counter.textContent = shown;
  });
});

// Long-running forms: show what is happening. data-busy is the title; data-busy-steps is an
// optional "|"-separated list shown as a progress list, advanced on a timer (an estimate, not a
// report from the server, so the last step stays "in progress" until the page changes).
(function () {
  var overlay = document.querySelector("[data-busy-overlay]");
  document.querySelectorAll("form[data-busy]").forEach(function (form) {
    form.addEventListener("submit", function () {
      var button = form.querySelector("button[type=submit], button:not([type])");
      if (button) { button.classList.add("busy"); button.setAttribute("aria-busy", "true"); }
      if (!overlay || !form.dataset.busySteps) {
        if (button) button.textContent = form.dataset.busy;
        return;
      }
      overlay.querySelector("[data-busy-title]").textContent = form.dataset.busy;
      var list = overlay.querySelector("[data-busy-steps]");
      list.innerHTML = "";
      var steps = form.dataset.busySteps.split("|").map(function (s) {
        var li = document.createElement("li");
        li.textContent = s;
        list.appendChild(li);
        return li;
      });
      overlay.hidden = false;
      var each = Number(form.dataset.busyStepMs || 5000), i = 0;
      steps[0].className = "is-doing";
      var timer = setInterval(function () {
        if (i >= steps.length - 1) { clearInterval(timer); return; }
        steps[i].className = "is-done";
        steps[++i].className = "is-doing";
      }, each);
    });
  });
  // Back-navigation from the result page restores this page from cache: hide the overlay.
  window.addEventListener("pageshow", function () {
    if (overlay) overlay.hidden = true;
    document.querySelectorAll(".busy").forEach(function (b) { b.classList.remove("busy"); });
  });
})();

// File input: highlight while dragging a file over it.
document.querySelectorAll("input[type=file]").forEach(function (input) {
  ["dragenter", "dragover"].forEach(function (t) { input.addEventListener(t, function () { input.classList.add("is-drag"); }); });
  ["dragleave", "drop"].forEach(function (t) { input.addEventListener(t, function () { input.classList.remove("is-drag"); }); });
});

// Filter selects apply immediately; the Apply button stays for keyboard and no-JS users.
document.querySelectorAll("select[data-autosubmit]").forEach(function (s) {
  s.addEventListener("change", function () { s.form.submit(); });
});
