// Staff workspace helpers: the Ctrl+K palette and the side drawer.
// Pure enhancement: without it the search button does nothing harmful and drawer links open as normal pages.
(function () {
  var html = function (s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); };

  // ---------------------------------------------------------------- Ctrl+K palette
  var box = document.createElement("div");
  box.className = "cmdk";
  box.hidden = true;
  box.innerHTML = '<div class="cmdk__box" role="dialog" aria-modal="true" aria-label="Search the workspace">' +
    '<label class="cmdk__field"><svg class="icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>' +
    '<input type="search" placeholder="Search pages, documents, requirement codes, employees, modules…" aria-label="Search" autocomplete="off" spellcheck="false"></label>' +
    '<div class="cmdk__list" role="listbox"></div>' +
    '<div class="cmdk__foot"><span><kbd>↑</kbd> <kbd>↓</kbd> move</span><span><kbd>Enter</kbd> open</span><span><kbd>Esc</kbd> close</span></div></div>';
  document.body.appendChild(box);
  var input = box.querySelector("input"), list = box.querySelector(".cmdk__list");
  var pages = [];                                   // every page the sidebar offers, including those shown as tabs
  try { pages = JSON.parse(document.getElementById("nav-pages").textContent); } catch (e) {}
  var results = [], on = 0, timer = null, seq = 0, lastFocus = null;

  function render(groups) {
    results = [];
    var out = "";
    groups.forEach(function (g) {
      if (!g.items.length) return;
      out += '<p class="cmdk__group">' + html(g.label) + "</p>";
      g.items.forEach(function (it) {
        out += '<a class="cmdk__item" role="option" href="' + html(it.url) + '" data-i="' + results.length + '">' +
          (it.code ? "<code>" + html(it.code) + "</code>" : "") + "<span>" + html(it.title) + "</span>" +
          (it.meta ? "<small>" + html(it.meta) + "</small>" : "") + "</a>";
        results.push(it);
      });
    });
    list.innerHTML = out || '<p class="cmdk__empty">Nothing found. Try a document code like GDP-01, a requirement code, or a name.</p>';
    move(0);
  }
  function move(n) {
    var items = list.querySelectorAll(".cmdk__item");
    if (!items.length) return;
    on = (n + items.length) % items.length;
    items.forEach(function (el, k) { el.classList.toggle("is-on", k === on); el.setAttribute("aria-selected", k === on ? "true" : "false"); });
    items[on].scrollIntoView({ block: "nearest" });
  }
  function localPages(q) {
    q = q.toLowerCase();
    return pages.filter(function (p) { return !q || p.title.toLowerCase().indexOf(q) >= 0; }).slice(0, q ? 5 : 12);
  }
  function query() {
    var q = input.value.trim(), mine = ++seq;
    var groups = [{ label: "Pages", items: localPages(q) }];
    render(groups);
    if (q.length < 2) return;
    clearTimeout(timer);
    timer = setTimeout(function () {
      fetch("/api/search?q=" + encodeURIComponent(q), { headers: { Accept: "application/json" } })
        .then(function (r) { return r.ok ? r.json() : { groups: [] }; })
        .then(function (data) { if (mine === seq) render(groups.concat(data.groups || [])); })
        .catch(function () {});
    }, 160);
  }
  function open() {
    lastFocus = document.activeElement;
    box.hidden = false;
    input.value = "";
    query();
    input.focus();
  }
  function close() {
    box.hidden = true;
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }
  input.addEventListener("input", query);
  box.addEventListener("click", function (e) { if (e.target === box) close(); });
  list.addEventListener("mousemove", function (e) {
    var a = e.target.closest(".cmdk__item");
    if (a && +a.dataset.i !== on) move(+a.dataset.i);
  });
  box.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { e.preventDefault(); close(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); move(on + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); move(on - 1); }
    else if (e.key === "Enter") {
      var a = list.querySelectorAll(".cmdk__item")[on];
      if (a) { e.preventDefault(); window.location.href = a.getAttribute("href"); }
    }
  });
  document.addEventListener("keydown", function (e) {
    var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); box.hidden ? open() : close(); }
    else if (e.key === "/" && !typing && box.hidden) { e.preventDefault(); open(); }
  });
  document.querySelectorAll("[data-cmdk-open]").forEach(function (b) { b.addEventListener("click", open); });

  // ---------------------------------------------------------------- side drawer
  // Links marked data-drawer open the target page's main content in a panel; "Open full page" keeps the normal route.
  var drawer = document.createElement("div");
  drawer.className = "drawer";
  drawer.hidden = true;
  drawer.innerHTML = '<div class="drawer__scrim" data-drawer-close></div><aside class="drawer__panel" role="dialog" aria-modal="true" aria-label="Details">' +
    '<div class="drawer__bar"><a data-drawer-full href="#">Open full page →</a>' +
    '<button type="button" class="iconbtn" data-drawer-close aria-label="Close">✕</button></div><div class="drawer__body"></div></aside>';
  document.body.appendChild(drawer);
  var body = drawer.querySelector(".drawer__body"), full = drawer.querySelector("[data-drawer-full]"), dseq = 0, opener = null;

  function openDrawer(url, from) {
    opener = from;
    var mine = ++dseq;
    full.href = url;
    body.innerHTML = '<p class="drawer__loading">Opening…</p>';
    drawer.hidden = false;
    document.documentElement.style.overflow = "hidden";
    drawer.querySelector(".iconbtn").focus();
    fetch(url, { headers: { Accept: "text/html" } }).then(function (r) {
      if (!r.ok || r.redirected) throw new Error("fallback");
      return r.text();
    }).then(function (text) {
      if (mine !== dseq) return;
      var main = new DOMParser().parseFromString(text, "text/html").querySelector("#main");
      if (!main) throw new Error("fallback");
      main.querySelectorAll(".flashes, .hubtabs, script").forEach(function (n) { n.remove(); });
      body.innerHTML = main.innerHTML;
      // A form without an action posts to the page it came from, not to the list the drawer is open on.
      body.querySelectorAll("form").forEach(function (f) { if (!f.getAttribute("action")) f.setAttribute("action", url); });
      body.querySelectorAll(".rise").forEach(function (n) { n.classList.add("is-in"); });
      body.scrollTop = 0;
    }).catch(function () { window.location.href = url; });
  }
  function closeDrawer() {
    drawer.hidden = true;
    document.documentElement.style.overflow = "";
    if (opener && opener.focus) opener.focus();
  }
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a[data-drawer]");
    if (!a || e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    openDrawer(a.getAttribute("href"), a);
  });
  drawer.addEventListener("click", function (e) { if (e.target.closest("[data-drawer-close]")) closeDrawer(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !drawer.hidden && box.hidden) closeDrawer(); });
})();
