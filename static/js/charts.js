// Small, dependency-free charts for staff pages (counting numbers and growing bars are in portal.js). Works offline; every number is also on the page as text.
//   [data-donut]            JSON [{key, label, value}] -> animated SVG ring (data-donut-unit="task|tasks");
//                           with data-donut-filter each segment is also a filter button
//   .cols [data-h]          column heights grow from 0 when in view
//   [data-filter-list]      cards filtered by [data-filter-search], and by any [data-set-filter] button
//   .flash--success         the message slides away after a few seconds (hovering keeps it)
(function () {
  var still = matchMedia("(prefers-reduced-motion: reduce)").matches;

  function whenSeen(el, fn) {
    if (still || !("IntersectionObserver" in window)) return fn();
    var io = new IntersectionObserver(function (entries) {
      if (entries[0].isIntersecting) { io.disconnect(); fn(); }
    }, { threshold: 0.2 });
    io.observe(el);
  }

  // ------------------------------------------------------------ donut
  var NS = "http://www.w3.org/2000/svg";
  document.querySelectorAll("[data-donut]").forEach(function (box) {
    var data = [];
    try { data = JSON.parse(box.getAttribute("data-donut")); } catch (e) { return; }
    var total = data.reduce(function (s, d) { return s + d.value; }, 0);
    total = Math.max(total, Number(box.getAttribute("data-donut-total")) || 0);   // a progress ring: the rest stays empty track
    if (!total) return;
    var unit = (box.getAttribute("data-donut-unit") || "file|files").split("|");
    var r = 42, c = 2 * Math.PI * r, gap = data.length > 1 ? 1.2 : 0;   // a thin surface gap between segments
    var svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 100 100");
    svg.setAttribute("class", "donut__svg");
    svg.setAttribute("aria-hidden", "true");
    var track = document.createElementNS(NS, "circle");
    track.setAttribute("cx", 50); track.setAttribute("cy", 50); track.setAttribute("r", r);
    track.setAttribute("class", "donut__track");
    svg.appendChild(track);
    var at = 0;
    data.forEach(function (d, i) {
      var len = c * d.value / total, seg = document.createElementNS(NS, "circle");
      seg.setAttribute("cx", 50); seg.setAttribute("cy", 50); seg.setAttribute("r", r);
      seg.setAttribute("class", "donut__seg donut__seg--" + d.key);
      seg.setAttribute("stroke-dasharray", Math.max(0.6, len - gap) + " " + c);
      seg.setAttribute("stroke-dashoffset", still ? -at : c);
      seg.setAttribute("data-tip", d.label + ": " + d.value + " " + (d.value === 1 ? unit[0] : unit[1]));
      if (box.hasAttribute("data-donut-filter")) seg.setAttribute("data-set-filter", "status:" + d.key);
      seg.style.transitionDelay = (still ? 0 : 120 * i) + "ms";
      seg.dataset.offset = -at;
      svg.appendChild(seg);
      at += len;
    });
    box.insertBefore(svg, box.firstChild);
    whenSeen(box, function () {
      svg.querySelectorAll(".donut__seg").forEach(function (s) { s.setAttribute("stroke-dashoffset", s.dataset.offset); });
    });
  });

  // ------------------------------------------------------------ bars outside a .rise section (portal.js fills those)
  document.querySelectorAll("[data-w]").forEach(function (b) {
    if (b.closest(".rise")) return;
    whenSeen(b.parentElement || b, function () { b.style.width = b.getAttribute("data-w"); });   // the empty bar has no area to observe
  });

  // ------------------------------------------------------------ columns that grow upward: [data-h] holds the height
  document.querySelectorAll(".cols").forEach(function (box) {
    var bars = box.querySelectorAll("[data-h]");
    if (!still) bars.forEach(function (b) { b.style.height = "0"; });
    whenSeen(box, function () {
      bars.forEach(function (b, i) { setTimeout(function () { b.style.height = b.getAttribute("data-h"); }, still ? 0 : 40 * i); });
    });
  });

  // ------------------------------------------------------------ card filters
  document.querySelectorAll("[data-filter-list]").forEach(function (list) {
    var scope = list.closest("[data-filter-scope]") || document;
    var search = scope.querySelector("[data-filter-search]");
    var chip = scope.querySelector("[data-filter-chip]");
    var none = scope.querySelector("[data-filter-none]");
    var picked = null;                                            // {field, value, label}

    function apply() {
      var q = (search && search.value || "").trim().toLowerCase(), shown = 0;
      list.querySelectorAll("[data-card]").forEach(function (card) {
        var ok = (!q || card.getAttribute("data-text").indexOf(q) !== -1) &&
                 (!picked || (card.getAttribute("data-" + picked.field) || "").split("|").indexOf(picked.value) !== -1);
        card.hidden = !ok;
        if (ok) shown++;
      });
      if (none) none.hidden = shown > 0;
      if (chip) {
        chip.hidden = !picked;
        if (picked) chip.querySelector("b").textContent = picked.label;
      }
      scope.querySelectorAll("[data-set-filter]").forEach(function (b) {
        var on = picked && b.getAttribute("data-set-filter") === picked.field + ":" + picked.value;
        b.classList.toggle("is-picked", !!on);
        if (b.tagName !== "circle") b.setAttribute("aria-pressed", on ? "true" : "false");
      });
    }
    if (search) search.addEventListener("input", apply);
    scope.addEventListener("click", function (e) {
      var b = e.target.closest && e.target.closest("[data-set-filter]");
      if (b) {
        var parts = b.getAttribute("data-set-filter").split(":"), value = parts.slice(1).join(":");
        var label = b.getAttribute("data-filter-label") || (b.getAttribute("data-tip") || value).split(":")[0];
        picked = picked && picked.field === parts[0] && picked.value === value ? null : { field: parts[0], value: value, label: label };
        apply();
        return;
      }
      if (e.target.closest && e.target.closest("[data-filter-clear]")) { picked = null; if (search) search.value = ""; apply(); }
    });
    apply();
  });

  // ------------------------------------------------------------ success messages leave after a few seconds; errors stay
  document.querySelectorAll(".flash--success").forEach(function (f) {
    var timer = setTimeout(leave, 5000);
    f.addEventListener("mouseenter", function () { clearTimeout(timer); });        // reading it keeps it open
    f.addEventListener("mouseleave", function () { timer = setTimeout(leave, 2000); });
    function leave() {
      if (still) { f.remove(); return; }
      f.classList.add("is-leaving");
      setTimeout(function () { f.remove(); }, 360);
    }
  });
})();
