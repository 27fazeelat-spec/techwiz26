// Workspace motion: the drifting aurora follows the pointer a little, cards tilt towards it, buttons ripple,
// and milestones get a short burst of confetti. Everything is decoration: pages work the same without it.
// Calm mode (the sparkle button in the top bar) or the system "reduce motion" setting turns the motion off.
(function () {
  var root = document.documentElement;
  var reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  var fine = matchMedia("(hover: hover) and (pointer: fine)").matches;
  function calm() { return reduce || root.dataset.calm === "on"; }

  // ------------------------------------------------------------ Calm mode, remembered on this device
  var toggle = document.querySelector("[data-calm-toggle]");
  function showCalm() {
    if (toggle) toggle.setAttribute("aria-pressed", root.dataset.calm === "on" ? "true" : "false");
  }
  if (toggle) {
    toggle.addEventListener("click", function () {
      if (root.dataset.calm === "on") delete root.dataset.calm; else root.dataset.calm = "on";
      try { localStorage.setItem("skillsprint-calm", root.dataset.calm === "on" ? "on" : "off"); } catch (e) {}
      showCalm();
    });
    showCalm();
  }

  // ------------------------------------------------------------ nothing moves while the tab is hidden
  document.addEventListener("visibilitychange", function () { root.classList.toggle("is-tab-hidden", document.hidden); });

  // ------------------------------------------------------------ the aurora leans towards the pointer
  var bg = document.querySelector(".aurora");
  if (bg && fine) {
    var px = 0, py = 0, queued = false;
    window.addEventListener("pointermove", function (e) {
      if (calm()) return;
      px = e.clientX / innerWidth - 0.5; py = e.clientY / innerHeight - 0.5;
      if (queued) return;
      queued = true;
      requestAnimationFrame(function () {
        bg.style.setProperty("--px", px.toFixed(3));
        bg.style.setProperty("--py", py.toFixed(3));
        queued = false;
      });
    }, { passive: true });
  }

  // ------------------------------------------------------------ cards tilt and catch the light
  var TILT = ".libcard, .personcard, .teamcard, .rolecard, .repcard, .chgcard, .polcard, a.libstat, .mtile, .course, .enext, .quizcta";
  if (fine) {
    document.querySelectorAll(TILT).forEach(function (el) { el.classList.add("tilt"); });
    document.addEventListener("pointermove", function (e) {
      var el = e.target.closest && e.target.closest(".tilt");
      if (!el || calm()) return;
      var r = el.getBoundingClientRect(), x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
      el.style.setProperty("--ry", ((x - 0.5) * 6).toFixed(2) + "deg");
      el.style.setProperty("--rx", ((0.5 - y) * 6).toFixed(2) + "deg");
      el.style.setProperty("--gx", (x * 100).toFixed(1) + "%");
      el.style.setProperty("--gy", (y * 100).toFixed(1) + "%");
    }, { passive: true });
    document.addEventListener("pointerout", function (e) {
      var el = e.target.closest && e.target.closest(".tilt");
      if (el && !el.contains(e.relatedTarget)) { el.style.removeProperty("--rx"); el.style.removeProperty("--ry"); }
    });
  }

  // ------------------------------------------------------------ a ripple where a button is pressed
  document.addEventListener("pointerdown", function (e) {
    var b = e.target.closest && e.target.closest(".btn, .hubtab, .topicchip, .jobpick__item");
    if (!b || calm()) return;
    var r = b.getBoundingClientRect(), d = Math.max(r.width, r.height) * 2, dot = document.createElement("span");
    dot.className = "ripple";
    dot.style.width = dot.style.height = d + "px";
    dot.style.left = (e.clientX - r.left - d / 2) + "px";
    dot.style.top = (e.clientY - r.top - d / 2) + "px";
    b.appendChild(dot);
    setTimeout(function () { dot.remove(); }, 650);
  });

  // ------------------------------------------------------------ confetti for milestones: window.celebrate()
  var COLOURS = ["#C4622D", "#E08A57", "#F2C9A8", "#5B6B3A", "#A3B476", "#E8B04A", "#FBF8F2"];
  function confetti(count) {
    if (reduce) return;
    var box = document.createElement("div");
    box.className = "confetti";
    box.setAttribute("aria-hidden", "true");
    for (var i = 0; i < (count || 70); i++) {
      var p = document.createElement("i");
      p.style.setProperty("--x", (Math.random() * 100).toFixed(1) + "vw");
      p.style.setProperty("--dx", ((Math.random() - 0.5) * 40).toFixed(1) + "vw");
      p.style.setProperty("--r", Math.round(Math.random() * 720 - 360) + "deg");
      p.style.setProperty("--d", (1.8 + Math.random() * 1.6).toFixed(2) + "s");
      p.style.setProperty("--dl", (Math.random() * 0.35).toFixed(2) + "s");
      p.style.background = COLOURS[i % COLOURS.length];
      if (i % 3 === 0) p.classList.add("is-round");
      box.appendChild(p);
    }
    document.body.appendChild(box);
    setTimeout(function () { box.remove(); }, 4200);
  }
  window.celebrate = confetti;
  // a milestone on the page ([data-celebrate="key"]) celebrates once, not on every visit
  var mark = document.querySelector("[data-celebrate]");
  if (mark) {
    var key = "skillsprint-celebrated-" + mark.dataset.celebrate, seen = false;
    try { seen = localStorage.getItem(key) === "1"; localStorage.setItem(key, "1"); } catch (e) { /* storage off: celebrate anyway */ }
    if (!seen && root.dataset.calm !== "on") setTimeout(function () { confetti(); }, 350);
  }
})();
