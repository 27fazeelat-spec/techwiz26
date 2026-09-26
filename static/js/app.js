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
  open.addEventListener("click", function () { if (matchMedia("(max-width: 960px)").matches) set(true); });
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

// ---------------------------------------------------------------- tooltips ([data-tip])
(function () {
  var tip = document.createElement("div");
  tip.className = "tip"; tip.setAttribute("role", "tooltip"); tip.hidden = true;
  document.body.appendChild(tip);
  var current = null;
  function place(el) {
    var r = el.getBoundingClientRect(), t = tip.getBoundingClientRect();
    var top = r.top - t.height - 8, left = r.left + r.width / 2 - t.width / 2;
    if (top < 8) top = r.bottom + 8;
    left = Math.max(8, Math.min(left, innerWidth - t.width - 8));
    tip.style.transform = "translate(" + Math.round(left) + "px," + Math.round(top) + "px)";
  }
  function show(el) {
    var text = el.getAttribute("data-tip");
    if (!text) return;
    if (el.classList.contains("navlink") && document.documentElement.dataset.nav === "expanded") return;
    current = el; tip.textContent = text; tip.hidden = false; place(el);
  }
  function hide() { current = null; tip.hidden = true; }
  document.addEventListener("mouseover", function (e) {
    var el = e.target.closest && e.target.closest("[data-tip]");
    if (el && el !== current) show(el);
    if (!el && current) hide();
  });
  document.addEventListener("focusin", function (e) { var el = e.target.closest && e.target.closest("[data-tip]"); if (el) show(el); });
  document.addEventListener("focusout", hide);
  window.addEventListener("scroll", hide, { passive: true });
})();

// ---------------------------------------------------------------- codes in text become references
(function () {
  var main = document.querySelector("[data-autoref]");
  if (!main) return;
  var docs = [];
  try { docs = JSON.parse(document.body.dataset.refDocs || "[]"); } catch (e) {}
  var docPattern = docs.length ? docs.slice().sort(function (a, b) { return b.length - a.length; })
    .map(function (d) { return d.replace(/[-]/g, "\\-"); }).join("|") : null;
  var pattern = new RegExp("\\b(R-[A-Z0-9]+(?:-[A-Z0-9]+)*-\\d{3})\\b|\\b(CF-\\d{4})\\b|\\b(RV-\\d{5})\\b" +
    (docPattern ? "|\\b(" + docPattern + ")\\b(?!-)" : ""), "g");
  var SKIP = /^(A|BUTTON|INPUT|TEXTAREA|SELECT|OPTION|SCRIPT|STYLE|LABEL)$/;
  var walker = document.createTreeWalker(main, NodeFilter.SHOW_TEXT, {
    acceptNode: function (n) {
      for (var p = n.parentNode; p && p !== main; p = p.parentNode) {
        if (SKIP.test(p.nodeName) || (p.classList && (p.classList.contains("ref") || p.hasAttribute("data-noref")))) return NodeFilter.FILTER_REJECT;
      }
      pattern.lastIndex = 0;
      return pattern.test(n.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
    }
  });
  var nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach(function (node) {
    var frag = document.createDocumentFragment(), text = node.nodeValue, last = 0, m;
    pattern.lastIndex = 0;
    while ((m = pattern.exec(text))) {
      frag.appendChild(document.createTextNode(text.slice(last, m.index)));
      var kind = m[1] ? "req" : m[2] ? "conflict" : m[3] ? "review" : "doc";
      var span = document.createElement("span");
      span.className = "ref"; span.tabIndex = 0; span.dataset.ref = kind + ":" + m[0]; span.textContent = m[0];
      frag.appendChild(span);
      last = m.index + m[0].length;
    }
    frag.appendChild(document.createTextNode(text.slice(last)));
    node.parentNode.replaceChild(frag, node);
  });
})();

// ---------------------------------------------------------------- hover cards for references ([data-ref])
(function () {
  var card = document.createElement("div");
  card.className = "refcard"; card.hidden = true; card.setAttribute("role", "dialog");
  document.body.appendChild(card);
  var cache = {}, timer = null, hideTimer = null, active = null;
  var esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;" }[c]; });
  };
  var KIND = { req: "Requirement", doc: "Document", conflict: "Conflict", review: "Review item" };
  function render(el, data) {
    var kind = el.dataset.ref.split(":")[0];
    if (!data) {
      card.innerHTML = "<p class=\"refcard__kind\">" + KIND[kind] + "</p><div class=\"refcard__skel\"></div><div class=\"refcard__skel refcard__skel--short\"></div>";
    } else if (data.error) {
      card.innerHTML = "<p class=\"refcard__kind\">" + KIND[kind] + "</p><p class=\"refcard__meta\">" + esc(data.error) + "</p>";
    } else {
      card.innerHTML = "<p class=\"refcard__kind\">" + esc(KIND[data.kind]) + " <span class=\"mono\">" + esc(data.code) + "</span></p>" +
        "<p class=\"refcard__title\">" + esc(data.title) + "</p>" +
        (data.source ? "<p class=\"refcard__source\">" + esc(data.source) + "</p>" : "") +
        (data.badges ? "<p class=\"refcard__badges\">" + data.badges.map(function (b) { return "<span class=\"tag\">" + esc(b) + "</span>"; }).join(" ") + "</p>" : "") +
        (data.meta ? "<p class=\"refcard__meta\">" + esc(data.meta) + "</p>" : "") +
        (data.decision ? "<p class=\"refcard__meta\"><strong>Decision:</strong> " + esc(data.decision) + "</p>" : "") +
        (data.warn ? "<p class=\"refcard__warn\">" + esc(data.warn) + "</p>" : "");
    }
    var r = el.getBoundingClientRect();
    card.hidden = false;
    var w = card.offsetWidth, h = card.offsetHeight;
    var top = r.bottom + 8;
    if (top + h > innerHeight - 8) top = Math.max(8, r.top - h - 8);
    var left = Math.max(8, Math.min(r.left, innerWidth - w - 8));
    card.style.transform = "translate(" + Math.round(left) + "px," + Math.round(top) + "px)";
  }
  function open(el) {
    active = el;
    var key = el.dataset.ref;
    if (cache[key]) { render(el, cache[key]); return; }
    render(el, null);
    var parts = key.split(":");
    fetch("/api/ref/" + parts[0] + "/" + encodeURIComponent(parts.slice(1).join(":")), { headers: { Accept: "application/json" } })
      .then(function (r) { return r.ok ? r.json() : { error: r.status === 403 ? "You do not have access to this." : "Not found." }; })
      .catch(function () { return { error: "Could not load the details." }; })
      .then(function (data) { cache[key] = data; if (active === el) render(el, data); });
  }
  function close() { active = null; card.hidden = true; }
  document.addEventListener("mouseover", function (e) {
    if (e.target.closest && e.target.closest(".refcard")) { clearTimeout(hideTimer); return; }
    var el = e.target.closest && e.target.closest("[data-ref]");
    clearTimeout(timer);
    if (el) { clearTimeout(hideTimer); if (el !== active) timer = setTimeout(function () { open(el); }, 220); }
    else if (active) { hideTimer = setTimeout(close, 180); }
  });
  document.addEventListener("focusin", function (e) { var el = e.target.closest && e.target.closest("[data-ref]"); if (el) open(el); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") close(); });
  window.addEventListener("scroll", close, { passive: true });
})();

// ---------------------------------------------------------------- sidebar: collapsed rail by default, remembered
(function () {
  var root = document.documentElement, btn = document.querySelector("[data-nav-toggle]");
  if (!btn) return;
  btn.setAttribute("aria-expanded", String(root.dataset.nav === "expanded"));
  btn.addEventListener("click", function () {
    if (matchMedia("(max-width: 960px)").matches) return;          // phones use the drawer
    var open = root.dataset.nav !== "expanded";
    if (open) root.dataset.nav = "expanded"; else delete root.dataset.nav;
    btn.setAttribute("aria-expanded", String(open));
    try { localStorage.setItem("skillsprint-nav", open ? "expanded" : "collapsed"); } catch (e) {}
  });
})();

// ---------------------------------------------------------------- guided tour, once per role (restart from Help)
(function () {
  var data = document.getElementById("tour-steps");
  if (!data) return;
  var steps = [];
  try { steps = JSON.parse(data.textContent); } catch (e) { return; }
  steps = steps.filter(function (s) { return !s.target || document.querySelector(s.target); });   // skip pages this role does not have
  if (!steps.length) return;
  var key = "skillsprint-tour-" + data.dataset.role;
  var start = document.querySelector("[data-tour-start]");
  var root = document.documentElement, layer = null, box = null, i = 0, navBefore;
  function end() {
    if (layer) layer.remove();
    layer = null;
    if (navBefore === undefined) delete root.dataset.nav; else root.dataset.nav = navBefore;
    try { localStorage.setItem(key, "done"); } catch (e) {}
  }
  function show() {
    var s = steps[i], target = s.target ? document.querySelector(s.target) : null;
    box.querySelector(".tour__step").textContent = (i + 1) + " of " + steps.length;
    box.querySelector(".tour__title").textContent = s.title;
    box.querySelector(".tour__text").textContent = s.text;
    box.querySelector("[data-tour-back]").hidden = i === 0;
    box.querySelector("[data-tour-next]").textContent = i === steps.length - 1 ? "Finish" : "Next";
    var hole = layer.querySelector(".tour__hole");
    if (target) {
      var r = target.getBoundingClientRect();
      hole.style.cssText = "display:block;left:" + (r.left - 6) + "px;top:" + (r.top - 6) + "px;width:" + (r.width + 12) + "px;height:" + (r.height + 12) + "px";
      var left = r.right + 18, top = Math.max(16, Math.min(innerHeight - 230, r.top - 10));
      if (left + 330 > innerWidth) { left = Math.max(16, Math.min(r.left, innerWidth - 346)); top = Math.min(innerHeight - 230, r.bottom + 16); }
      box.style.transform = "translate(" + Math.round(left) + "px," + Math.round(top) + "px)";
    } else {
      hole.style.cssText = "display:none";
      box.style.transform = "translate(" + Math.round(innerWidth / 2 - 165) + "px," + Math.round(innerHeight / 2 - 110) + "px)";
    }
  }
  function begin() {
    if (layer || matchMedia("(max-width: 960px)").matches) return;
    navBefore = root.dataset.nav;
    root.dataset.nav = "expanded";
    layer = document.createElement("div");
    layer.className = "tour";
    layer.innerHTML = "<div class=\"tour__hole\"></div><div class=\"tour__box\" role=\"dialog\" aria-live=\"polite\">" +
      "<p class=\"tour__step\"></p><p class=\"tour__title\"></p><p class=\"tour__text\"></p>" +
      "<div class=\"tour__actions\"><button type=\"button\" class=\"btn btn--ghost btn--sm\" data-tour-skip>Skip tour</button>" +
      "<span style=\"flex:1\"></span><button type=\"button\" class=\"btn btn--sm\" data-tour-back>Back</button>" +
      "<button type=\"button\" class=\"btn btn--primary btn--sm\" data-tour-next>Next</button></div></div>";
    document.body.appendChild(layer);
    box = layer.querySelector(".tour__box");
    i = 0;
    layer.querySelector("[data-tour-skip]").onclick = end;
    layer.querySelector("[data-tour-back]").onclick = function () { i = Math.max(0, i - 1); show(); };
    layer.querySelector("[data-tour-next]").onclick = function () { if (i === steps.length - 1) end(); else { i++; show(); } };
    setTimeout(show, 280);                    // after the sidebar has expanded
  }
  if (start) start.addEventListener("click", begin);
  var seen = null;
  try { seen = localStorage.getItem(key); } catch (e) {}
  if (!seen && data.dataset.auto === "1") setTimeout(begin, 700);
})();

// ---------------------------------------------------------------- bulk selection in the review queue
(function () {
  var form = document.querySelector("[data-bulk]");
  if (!form) return;
  var bar = form.querySelector("[data-bulkbar]"), counter = form.querySelector("[data-picked]"), all = form.querySelector("[data-pick-all]");
  function update() {
    var n = form.querySelectorAll("input[name=item]:checked").length;
    if (counter) counter.textContent = n;
    if (bar) bar.hidden = n === 0;
  }
  form.addEventListener("change", function (e) {
    if (e.target === all) form.querySelectorAll("input[name=item]").forEach(function (c) { c.checked = all.checked; });
    update();
  });
})();

// ---------------------------------------------------------------- tabs ([data-tabs] + [data-tabpanel]); the tab is kept in the URL hash
(function () {
  var nav = document.querySelector("[data-tabs]");
  if (!nav) return;
  var buttons = nav.querySelectorAll("[data-tab]");
  function select(name) {
    var found = false;
    buttons.forEach(function (b) { var on = b.dataset.tab === name; b.classList.toggle("is-on", on); b.setAttribute("aria-selected", String(on)); found = found || on; });
    if (!found) return false;
    document.querySelectorAll("[data-tabpanel]").forEach(function (p) { p.classList.toggle("is-hidden", p.dataset.tabpanel !== name); });
    return true;
  }
  nav.addEventListener("click", function (e) {
    var b = e.target.closest("[data-tab]");
    if (!b) return;
    select(b.dataset.tab);
    history.replaceState(null, "", "#" + b.dataset.tab);
  });
  var hash = location.hash.replace("#", "");
  if (!(hash && select(hash))) {
    var target = hash && document.getElementById(hash);          // a link to an item opens its tab
    var panel = target && target.closest("[data-tabpanel]");
    select(panel ? panel.dataset.tabpanel : "overview");
    if (target) target.scrollIntoView();
  }
  window.addEventListener("hashchange", function () {           // e.g. a finding links to an item in Modules
    var id = location.hash.replace("#", ""), el = id && document.getElementById(id);
    var panel = el && el.closest("[data-tabpanel]");
    if (panel) { select(panel.dataset.tabpanel); el.scrollIntoView({ block: "center" }); }
  });
})();
