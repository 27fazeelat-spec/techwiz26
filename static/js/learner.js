// Learner experience: hero carousel, floating top bar, scroll parallax and card spotlights.
// Pure enhancement: without it the first slide shows and every link still works.
(function () {
  var body = document.body;
  var reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  var fine = matchMedia("(hover: hover) and (pointer: fine)").matches;

  // the top bar floats over the hero, then turns solid once the page scrolls
  if (body.classList.contains("has-hero")) {
    var onScroll = function () { body.classList.toggle("is-scrolled", window.scrollY > 40); };
    onScroll();
    addEventListener("scroll", onScroll, { passive: true });
  }

  // ---------- hero carousel ----------
  var hero = document.querySelector("[data-carousel]");
  if (hero) {
    var slides = Array.prototype.slice.call(hero.querySelectorAll("[data-lslide]"));
    var tabs = Array.prototype.slice.call(hero.querySelectorAll("[data-go]"));
    var cur = 0, cleanup = null;
    hero.classList.add("js-carousel");
    slides.forEach(function (s, k) { s.hidden = false; s.setAttribute("aria-hidden", k === 0 ? "false" : "true"); });

    var go = function (n) {
      n = (n + slides.length) % slides.length;
      if (n === cur) return;
      var prev = slides[cur];
      slides.forEach(function (s) { s.classList.remove("is-prev", "is-entering"); });
      prev.classList.remove("is-active");
      prev.classList.add("is-prev");
      slides[n].classList.add("is-active", "is-entering");
      clearTimeout(cleanup);
      cleanup = setTimeout(function () { prev.classList.remove("is-prev"); slides[n].classList.remove("is-entering"); }, 1300);
      tabs.forEach(function (t, k) { t.classList.remove("is-active"); t.setAttribute("aria-selected", k === n ? "true" : "false"); });
      void tabs[n].offsetWidth;                                   // restart the timer line
      tabs[n].classList.add("is-active");
      slides.forEach(function (s, k) { s.setAttribute("aria-hidden", k === n ? "false" : "true"); });
      cur = n;
    };

    tabs.forEach(function (t) { t.addEventListener("click", function () { go(parseInt(t.dataset.go, 10)); }); });
    hero.querySelector("[data-prev]").addEventListener("click", function () { go(cur - 1); });
    hero.querySelector("[data-next]").addEventListener("click", function () { go(cur + 1); });
    // autoplay: the active tab's line fills over a few seconds; when it ends, move on
    hero.addEventListener("animationend", function (e) { if (e.animationName === "ltabfill") go(cur + 1); });
    var pause = function () { hero.classList.add("is-paused"); }, resume = function () { hero.classList.remove("is-paused"); };
    hero.addEventListener("pointerenter", pause);
    hero.addEventListener("pointerleave", resume);
    hero.addEventListener("focusin", pause);
    hero.addEventListener("focusout", resume);
    document.addEventListener("visibilitychange", function () { document.hidden ? pause() : resume(); });
    hero.addEventListener("keydown", function (e) {
      if (e.key === "ArrowRight") { e.preventDefault(); go(cur + 1); }
      if (e.key === "ArrowLeft") { e.preventDefault(); go(cur - 1); }
    });
    // swipe on touch screens
    var sx = null;
    hero.addEventListener("pointerdown", function (e) { if (e.pointerType !== "mouse") sx = e.clientX; });
    hero.addEventListener("pointerup", function (e) {
      if (sx === null) return;
      var dx = e.clientX - sx; sx = null;
      if (Math.abs(dx) > 50) go(cur + (dx < 0 ? 1 : -1));
    });
    // the photo drifts gently against the mouse
    if (fine && !reduce) {
      hero.addEventListener("pointermove", function (e) {
        var r = hero.getBoundingClientRect();
        hero.style.setProperty("--px", (((e.clientX - r.left) / r.width - 0.5) * -22).toFixed(1) + "px");
        hero.style.setProperty("--py", (((e.clientY - r.top) / r.height - 0.5) * -14).toFixed(1) + "px");
      });
    }
  }

  // ---------- scroll parallax for photo bands ----------
  var bands = Array.prototype.slice.call(document.querySelectorAll("[data-parallax]"));
  if (!reduce && (bands.length || hero)) {
    var ticking = false;
    var update = function () {
      ticking = false;
      var vh = window.innerHeight;
      bands.forEach(function (el) {
        var r = el.getBoundingClientRect();
        if (r.bottom < 0 || r.top > vh) return;
        var off = Math.max(-70, Math.min(70, (r.top + r.height / 2 - vh / 2) * -0.12));
        el.style.setProperty("--par", off.toFixed(1) + "px");
      });
      if (hero && window.scrollY < vh) hero.style.setProperty("--hs", (window.scrollY * 0.3).toFixed(1) + "px");
    };
    update();
    addEventListener("scroll", function () { if (!ticking) { ticking = true; requestAnimationFrame(update); } }, { passive: true });
  }

  // ---------- spotlight on learner cards (portal.js moves the light) ----------
  if (fine && !reduce) {
    document.querySelectorAll(".mtile, .jstep__card, .course, .certteaser").forEach(function (el) { el.classList.add("spot"); });
  }
})();
