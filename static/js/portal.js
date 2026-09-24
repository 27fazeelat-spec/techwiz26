// Workspace polish: custom cursor, spotlight, tilt, magnetic buttons, counters, entrance motion, greeting.
// Pure enhancement: every page works without it, and motion is skipped when the user prefers less.
(function () {
  var root = document.documentElement;
  var reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  var fine = matchMedia("(hover: hover) and (pointer: fine)").matches;

  // greeting by the viewer's own clock
  document.querySelectorAll("[data-greeting]").forEach(function (el) {
    var h = new Date().getHours();
    el.textContent = h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
  });

  // entrance: cards rise in as they reach the viewport; bars and rings fill
  var io = "IntersectionObserver" in window && !reduce ? new IntersectionObserver(function (entries) {
    entries.forEach(function (e) { if (e.isIntersecting) { reveal(e.target); io.unobserve(e.target); } });
  }, { threshold: 0.12 }) : null;
  function reveal(el) {
    el.classList.add("is-in");
    el.querySelectorAll("[data-w]").forEach(function (b) { b.style.width = b.dataset.w; });
    el.querySelectorAll("[data-count]").forEach(count);
    if (el.dataset.w) el.style.width = el.dataset.w;
    if (el.dataset.count) count(el);
  }
  document.querySelectorAll(".rise, [data-reveal]").forEach(function (el, i) {
    if (!io) { reveal(el); return; }
    if (el.classList.contains("rise")) el.style.transitionDelay = Math.min(i, 8) * 45 + "ms";
    io.observe(el);
  });

  function count(el) {
    if (el.dataset.counted) return;
    el.dataset.counted = "1";
    var target = parseFloat(el.dataset.count), dec = parseInt(el.dataset.decimals || "0", 10);
    if (reduce || isNaN(target)) { el.textContent = isNaN(target) ? el.textContent : target.toFixed(dec); return; }
    var start = performance.now();
    (function step(now) {
      var p = Math.min(1, (now - start) / 1300), v = target * (1 - Math.pow(1 - p, 4));
      el.textContent = v.toFixed(dec);
      if (p < 1) requestAnimationFrame(step);
    })(start);
  }

  if (reduce || !fine) return;

  // spotlight on cards
  var SPOT = ".kpi, .panel, .flow__step, .modcard, .pcard, .kindcard, .teamcard, .upnext li a";
  document.querySelectorAll(SPOT).forEach(function (el) { el.classList.add("spot"); });
  document.addEventListener("pointermove", function (e) {
    var el = e.target.closest && e.target.closest(".spot");
    if (!el) return;
    var r = el.getBoundingClientRect();
    el.style.setProperty("--sx", (e.clientX - r.left) + "px");
    el.style.setProperty("--sy", (e.clientY - r.top) + "px");
  }, { passive: true });

  // 3D tilt
  document.querySelectorAll("[data-tilt]").forEach(function (el) {
    el.addEventListener("pointermove", function (e) {
      var r = el.getBoundingClientRect(), x = (e.clientX - r.left) / r.width - 0.5, y = (e.clientY - r.top) / r.height - 0.5;
      el.style.setProperty("--ry", (x * 7).toFixed(2) + "deg");
      el.style.setProperty("--rx", (-y * 7).toFixed(2) + "deg");
    });
    el.addEventListener("pointerleave", function () { el.style.setProperty("--rx", "0deg"); el.style.setProperty("--ry", "0deg"); });
  });

  // magnetic primary actions
  document.querySelectorAll(".btn--primary, .btn--gold, [data-magnetic]").forEach(function (el) {
    el.addEventListener("pointermove", function (e) {
      var r = el.getBoundingClientRect();
      el.style.transform = "translate(" + ((e.clientX - r.left - r.width / 2) * 0.18).toFixed(1) + "px," + ((e.clientY - r.top - r.height / 2) * 0.28).toFixed(1) + "px)";
    });
    el.addEventListener("pointerleave", function () { el.style.transform = ""; });
  });

  // custom cursor
  var cursor = document.querySelector(".cursor");
  if (!cursor) return;
  root.classList.add("has-cursor");
  var dot = cursor.querySelector(".cursor__dot"), ring = cursor.querySelector(".cursor__ring"), label = cursor.querySelector(".cursor__label");
  var mx = innerWidth / 2, my = innerHeight / 2, rx = mx, ry = my, seen = false;
  var INTERACTIVE = "a, button, summary, select, label, [role=button], [data-cursor], [data-ref], .pick";
  var TEXT = "input:not([type=checkbox]):not([type=radio]):not([type=submit]):not([type=button]), textarea";
  document.addEventListener("pointermove", function (e) {
    mx = e.clientX; my = e.clientY;
    if (!seen) { rx = mx; ry = my; seen = true; cursor.classList.remove("is-hidden"); }
    dot.style.transform = "translate3d(" + mx + "px," + my + "px,0)";
    var t = e.target, text = t.closest && t.closest(TEXT), hit = !text && t.closest && t.closest(INTERACTIVE);
    var words = hit && hit.getAttribute("data-cursor");
    cursor.classList.toggle("is-text", !!text);
    cursor.classList.toggle("is-label", !!words);
    cursor.classList.toggle("is-hover", !!hit && !words);
    if (words) label.textContent = words;
  }, { passive: true });
  document.addEventListener("pointerdown", function (e) {
    cursor.classList.add("is-down");
    var b = document.createElement("span");
    b.className = "cursor__burst";
    b.style.setProperty("--t", "translate3d(" + e.clientX + "px," + e.clientY + "px,0)");
    document.body.appendChild(b);
    setTimeout(function () { b.remove(); }, 650);
  });
  document.addEventListener("pointerup", function () { cursor.classList.remove("is-down"); });
  document.documentElement.addEventListener("pointerleave", function () { cursor.classList.add("is-hidden"); seen = false; });
  (function frame() {
    rx += (mx - rx) * 0.2; ry += (my - ry) * 0.2;
    ring.style.transform = "translate3d(" + rx.toFixed(2) + "px," + ry.toFixed(2) + "px,0)";
    requestAnimationFrame(frame);
  })();
})();

// Quiz: one question at a time, keyboard friendly, with a review step. Without JS every question shows at once.
(function () {
  var form = document.querySelector("[data-quiz]");
  if (!form) return;
  document.documentElement.classList.add("js-quiz");
  var slides = Array.prototype.slice.call(form.querySelectorAll("[data-slide]"));
  var questions = slides.filter(function (s) { return !s.hasAttribute("data-review"); });
  var bar = document.querySelector("[data-quiz-bar]");
  var prev = form.querySelector("[data-quiz-prev]");
  var next = form.querySelector("[data-quiz-next]");
  var submit = form.querySelector("[data-quiz-submit]");
  var reviewList = form.querySelector("[data-review-list]");
  var i = 0, timer = null;

  function answered(slide) { return !!slide.querySelector("input:checked"); }
  function isReview(slide) { return slide.hasAttribute("data-review"); }

  function buildReview() {
    reviewList.innerHTML = "";
    questions.forEach(function (s, k) {
      var li = document.createElement("li");
      var picked = Array.prototype.map.call(s.querySelectorAll("input:checked"), function (inp) {
        return inp.closest(".qopt").querySelector(".qopt__key").textContent;
      });
      var text = s.querySelector(".quizq__text").textContent.trim();
      li.textContent = (text.length > 90 ? text.slice(0, 88) + "…" : text) + " — " + (picked.length ? picked.join(", ") : "not answered");
      if (!picked.length) li.className = "is-missing";
      var edit = document.createElement("button");
      edit.type = "button";
      edit.textContent = "change";
      edit.addEventListener("click", function () { show(k); });
      li.appendChild(edit);
      reviewList.appendChild(li);
    });
    submit.disabled = questions.some(function (s) { return !answered(s); });
  }

  function show(n) {
    clearTimeout(timer);
    i = Math.max(0, Math.min(slides.length - 1, n));
    slides.forEach(function (s, k) { s.classList.toggle("is-current", k === i); });
    var onReview = isReview(slides[i]);
    if (bar) bar.style.width = (100 * (onReview ? questions.length : i) / questions.length) + "%";
    prev.style.visibility = i === 0 ? "hidden" : "visible";
    next.hidden = onReview;
    submit.hidden = !onReview;
    next.disabled = !onReview && !answered(slides[i]);
    if (onReview) buildReview();
    else {
      var first = slides[i].querySelector("input:checked") || slides[i].querySelector("input");
      if (first) first.focus({ preventScroll: true });
    }
  }

  form.addEventListener("change", function () {
    var slide = slides[i];
    if (isReview(slide)) return;
    next.disabled = !answered(slide);
    // A single-answer question moves on by itself after a short pause.
    if (slide.querySelector("input[type=radio]:checked")) {
      clearTimeout(timer);
      timer = setTimeout(function () { if (slides[i] === slide) show(i + 1); }, 450);
    }
  });
  prev.addEventListener("click", function () { show(i - 1); });
  next.addEventListener("click", function () { if (answered(slides[i])) show(i + 1); });
  form.addEventListener("keydown", function (e) {
    var slide = slides[i];
    if (isReview(slide) || e.ctrlKey || e.metaKey || e.altKey) return;
    var inputs = slide.querySelectorAll("input");
    var key = (e.key || "").toLowerCase();
    var k = "123456789".indexOf(key);
    if (k < 0) k = "abcdefgh".indexOf(key);
    if (key.length === 1 && k >= 0 && inputs[k]) { e.preventDefault(); inputs[k].click(); }
    else if (e.key === "Enter") { e.preventDefault(); if (answered(slide)) show(i + 1); }
  });
  show(0);
})();
