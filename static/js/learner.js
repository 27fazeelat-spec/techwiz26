// Learner home: the highlights carousel. One story at a time, cross-faded; it pauses while you read.
// Pure enhancement: without it the first story shows and every link still works.
(function () {
  var hero = document.querySelector("[data-carousel]");
  if (!hero) return;
  var slides = Array.prototype.slice.call(hero.querySelectorAll("[data-lslide]"));
  var tabs = Array.prototype.slice.call(hero.querySelectorAll("[data-go]"));
  if (slides.length < 2) return;
  var cur = 0;
  slides.forEach(function (s, k) { s.hidden = false; s.setAttribute("aria-hidden", k === 0 ? "false" : "true"); });

  function go(n) {
    n = (n + slides.length) % slides.length;
    if (n === cur) return;
    slides[cur].classList.remove("is-active");
    slides[n].classList.add("is-active");
    tabs.forEach(function (t, k) { t.classList.remove("is-active"); t.setAttribute("aria-selected", k === n ? "true" : "false"); });
    void tabs[n].offsetWidth;                                     // restart the timer line
    tabs[n].classList.add("is-active");
    slides.forEach(function (s, k) { s.setAttribute("aria-hidden", k === n ? "false" : "true"); });
    cur = n;
  }

  tabs.forEach(function (t) { t.addEventListener("click", function () { go(parseInt(t.dataset.go, 10)); }); });
  hero.querySelector("[data-prev]").addEventListener("click", function () { go(cur - 1); });
  hero.querySelector("[data-next]").addEventListener("click", function () { go(cur + 1); });
  // autoplay: the active tab's line fills slowly; when it ends, the next story shows
  hero.addEventListener("animationend", function (e) { if (e.animationName === "ltabfill") go(cur + 1); });
  function pause() { hero.classList.add("is-paused"); }
  function resume() { hero.classList.remove("is-paused"); }
  hero.addEventListener("pointerenter", pause);
  hero.addEventListener("pointerleave", resume);
  hero.addEventListener("focusin", pause);
  hero.addEventListener("focusout", resume);
  document.addEventListener("visibilitychange", function () { document.hidden ? pause() : resume(); });
  hero.addEventListener("keydown", function (e) {
    if (e.key === "ArrowRight") { e.preventDefault(); go(cur + 1); }
    if (e.key === "ArrowLeft") { e.preventDefault(); go(cur - 1); }
  });
  var sx = null;                                                  // swipe on touch screens
  hero.addEventListener("pointerdown", function (e) { if (e.pointerType !== "mouse") sx = e.clientX; });
  hero.addEventListener("pointerup", function (e) {
    if (sx === null) return;
    var dx = e.clientX - sx; sx = null;
    if (Math.abs(dx) > 50) go(cur + (dx < 0 ? 1 : -1));
  });
})();
