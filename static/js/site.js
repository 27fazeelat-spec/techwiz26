// SkillSprint public site: cursor, reveal, spotlight, magnetic buttons, tilt, counters, console demo.
// Everything is progressive: without JS (or with reduced motion) the pages are complete and static.
(function () {
  var root = document.documentElement;
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var fine = window.matchMedia("(hover: hover) and (pointer: fine)").matches;
  var lerp = function (a, b, t) { return a + (b - a) * t; };

  // ------------------------------------------------------------ theme toggle (shared key with the app)
  var toggle = document.querySelector("[data-theme-toggle]");
  if (toggle) {
    var current = function () { return root.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"); };
    toggle.addEventListener("click", function () {
      var next = current() === "dark" ? "light" : "dark";
      root.dataset.theme = next;
      try { localStorage.setItem("skillsprint-theme", next); } catch (e) {}
    });
  }

  // ------------------------------------------------------------ nav: solid after scrolling; mobile sheet
  var nav = document.querySelector("[data-nav]");
  if (nav) {
    var onScroll = function () { nav.classList.toggle("is-scrolled", window.scrollY > 24); };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    var open = nav.querySelector("[data-menu-open]"), sheet = nav.querySelector("[data-menu]");
    if (open && sheet) open.addEventListener("click", function () {
      sheet.hidden = !sheet.hidden;
      open.setAttribute("aria-expanded", String(!sheet.hidden));
      nav.classList.add("is-scrolled");
    });
  }

  // ------------------------------------------------------------ split headline into words
  document.querySelectorAll("[data-split]").forEach(function (el) {
    var i = 0;
    var walk = function (node) {
      Array.prototype.slice.call(node.childNodes).forEach(function (child) {
        if (child.nodeType === 3) {
          var frag = document.createDocumentFragment();
          child.textContent.split(/(\s+)/).forEach(function (part) {
            if (!part) return;
            if (/^\s+$/.test(part)) { frag.appendChild(document.createTextNode(part)); return; }
            var w = document.createElement("span"); w.className = "word";
            var inner = document.createElement("span"); inner.textContent = part; inner.style.setProperty("--i", i++);
            w.appendChild(inner); frag.appendChild(w);
          });
          child.parentNode.replaceChild(frag, child);
        } else if (child.nodeType === 1) { walk(child); }
      });
    };
    walk(el);
  });

  // ------------------------------------------------------------ scroll reveal (+ one-shot triggers)
  var triggers = [];
  var io = "IntersectionObserver" in window ? new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (!e.isIntersecting) return;
      e.target.classList.add("is-in");
      e.target.querySelectorAll(".word").forEach(function (w) { w.classList.add("is-in"); });
      io.unobserve(e.target);
      triggers.forEach(function (t) { if (t.el === e.target || e.target.contains(t.el)) t.run(); });
    });
  }, { threshold: 0.18, rootMargin: "0px 0px -6% 0px" }) : null;
  var revealables = document.querySelectorAll(".reveal, .principle, .meters-demo");
  revealables.forEach(function (el, n) {
    if (!io || reduce) { el.classList.add("is-in"); return; }
    if (el.closest(".stats, .bento, .flowline, .cards3, .statements")) el.style.transitionDelay = (n % 4) * 80 + "ms";
    io.observe(el);
  });
  if (reduce) document.querySelectorAll(".word").forEach(function (w) { w.classList.add("is-in"); });

  // ------------------------------------------------------------ counters
  document.querySelectorAll("[data-count]").forEach(function (el) {
    var target = parseFloat(el.dataset.count), decimals = parseInt(el.dataset.decimals || "0", 10);
    var show = function (v) { el.textContent = v.toFixed(decimals); };
    if (reduce || !io) { show(target); return; }
    var run = function () {
      var start = performance.now(), dur = 1600;
      (function step(now) {
        var p = Math.min(1, (now - start) / dur), eased = 1 - Math.pow(1 - p, 4);
        show(target * eased);
        if (p < 1) requestAnimationFrame(step);
      })(start);
    };
    var host = el.closest(".reveal") || el;
    if (host.classList.contains("is-in")) run(); else triggers.push({ el: host, run: run });
  });

  // ------------------------------------------------------------ console demo: checks tick one by one, then the stamp
  var checks = document.querySelector("[data-checks]"), stamp = document.querySelector("[data-stamp]");
  if (checks && stamp) {
    var items = checks.querySelectorAll("li");
    var play = function () {
      items.forEach(function (li) { li.className = ""; });
      stamp.classList.remove("is-on");
      if (reduce) { items.forEach(function (li) { li.className = "is-done"; }); stamp.classList.add("is-on"); return; }
      var i = 0;
      var next = function () {
        if (i > 0) items[i - 1].className = "is-done";
        if (i === items.length) { setTimeout(function () { stamp.classList.add("is-on"); }, 250); setTimeout(play, 5200); return; }
        items[i].className = "is-doing"; i++;
        setTimeout(next, 700);
      };
      setTimeout(next, 900);
    };
    play();
  }

  // ------------------------------------------------------------ how-it-works line fills as you scroll
  var flow = document.querySelector("[data-flowline]");
  if (flow && !reduce) {
    var fill = function () {
      var r = flow.getBoundingClientRect(), vh = window.innerHeight;
      var p = Math.min(1, Math.max(0, (vh * 0.85 - r.top) / (r.height + vh * 0.4)));
      flow.style.setProperty("--progress", p.toFixed(3));
    };
    fill(); window.addEventListener("scroll", fill, { passive: true });
  }

  // ------------------------------------------------------------ password show/hide and caps-lock hint
  document.querySelectorAll("[data-reveal-password]").forEach(function (btn) {
    var input = document.getElementById(btn.dataset.revealPassword);
    btn.addEventListener("click", function () {
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      btn.textContent = show ? "Hide" : "Show";
      btn.setAttribute("aria-pressed", String(show));
      input.focus();
    });
    var caps = document.querySelector("[data-caps]");
    if (caps) input.addEventListener("keyup", function (e) { caps.hidden = !(e.getModifierState && e.getModifierState("CapsLock")); });
  });
  document.querySelectorAll("form[data-submit-busy]").forEach(function (f) {
    f.addEventListener("submit", function () { var b = f.querySelector("button[type=submit]"); if (b) { b.disabled = true; b.textContent = f.dataset.submitBusy; } });
  });

  if (reduce || !fine) return;          // the rest is pointer-driven polish

  // ------------------------------------------------------------ spotlight on cards and dark sections
  document.addEventListener("pointermove", function (e) {
    var card = e.target.closest && e.target.closest("[data-spot]");
    if (card) {
      var r = card.getBoundingClientRect();
      card.style.setProperty("--sx", (e.clientX - r.left) + "px");
      card.style.setProperty("--sy", (e.clientY - r.top) + "px");
    }
    var dark = e.target.closest && e.target.closest("[data-spotlight]");
    document.querySelectorAll("[data-spotlight]").forEach(function (d) { if (d !== dark) d.style.setProperty("--spot-o", 0); });
    if (dark) {
      var b = dark.getBoundingClientRect();
      dark.style.setProperty("--mx", (e.clientX - b.left) + "px");
      dark.style.setProperty("--my", (e.clientY - b.top) + "px");
      dark.style.setProperty("--spot-o", 1);
    }
  }, { passive: true });

  // ------------------------------------------------------------ 3D tilt
  document.querySelectorAll("[data-tilt]").forEach(function (el) {
    el.addEventListener("pointermove", function (e) {
      var r = el.getBoundingClientRect();
      var x = (e.clientX - r.left) / r.width - 0.5, y = (e.clientY - r.top) / r.height - 0.5;
      el.style.setProperty("--ry", (x * 8).toFixed(2) + "deg");
      el.style.setProperty("--rx", (-y * 8).toFixed(2) + "deg");
    });
    el.addEventListener("pointerleave", function () { el.style.setProperty("--rx", "0deg"); el.style.setProperty("--ry", "0deg"); });
  });

  // ------------------------------------------------------------ magnetic buttons
  document.querySelectorAll("[data-magnetic]").forEach(function (el) {
    el.addEventListener("pointermove", function (e) {
      var r = el.getBoundingClientRect();
      var x = e.clientX - (r.left + r.width / 2), y = e.clientY - (r.top + r.height / 2);
      el.style.transform = "translate(" + (x * 0.22).toFixed(1) + "px," + (y * 0.32).toFixed(1) + "px)";
    });
    el.addEventListener("pointerleave", function () { el.style.transform = ""; });
  });

  // ------------------------------------------------------------ custom cursor
  var cursor = document.querySelector(".cursor");
  if (!cursor) return;
  root.classList.add("has-cursor");
  var dot = cursor.querySelector(".cursor__dot"), ring = cursor.querySelector(".cursor__ring"), label = cursor.querySelector(".cursor__label");
  var mx = innerWidth / 2, my = innerHeight / 2, rx = mx, ry = my, seen = false;
  var INTERACTIVE = "a, button, [data-cursor], label, summary, select, [role=button]";
  var TEXT = "input:not([type=checkbox]):not([type=radio]):not([type=submit]), textarea";

  document.addEventListener("pointermove", function (e) {
    mx = e.clientX; my = e.clientY;
    if (!seen) { rx = mx; ry = my; seen = true; cursor.classList.remove("is-hidden"); }
    dot.style.transform = "translate3d(" + mx + "px," + my + "px,0)";
    var t = e.target;
    var text = t.closest && t.closest(TEXT);
    var hit = !text && t.closest && t.closest(INTERACTIVE);
    cursor.classList.toggle("is-text", !!text);
    var words = hit && hit.getAttribute("data-cursor");
    cursor.classList.toggle("is-label", !!words);
    cursor.classList.toggle("is-hover", !!hit && !words);
    if (words) label.textContent = words;
  }, { passive: true });
  document.addEventListener("pointerdown", function (e) {
    cursor.classList.add("is-down");
    var burst = document.createElement("span");
    burst.className = "cursor__burst";
    burst.style.setProperty("--t", "translate3d(" + e.clientX + "px," + e.clientY + "px,0)");
    document.body.appendChild(burst);
    setTimeout(function () { burst.remove(); }, 650);
  });
  document.addEventListener("pointerup", function () { cursor.classList.remove("is-down"); });
  document.addEventListener("pointerleave", function () { cursor.classList.add("is-hidden"); seen = false; });
  document.addEventListener("pointerenter", function () { cursor.classList.remove("is-hidden"); });

  (function frame() {
    rx = lerp(rx, mx, 0.18); ry = lerp(ry, my, 0.18);
    ring.style.transform = "translate3d(" + rx.toFixed(2) + "px," + ry.toFixed(2) + "px,0)";
    requestAnimationFrame(frame);
  })();
})();
