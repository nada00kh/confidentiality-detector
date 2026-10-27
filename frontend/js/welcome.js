// Welcome page: plays the intro, then opens the chosen area with a short scan-line transition.
// There is no sign-in yet: Employee opens the workspace, Administrator opens the dashboard.
// Extras: a giant W behind the page that the scan line crosses every few seconds (pure CSS),
// logo eyes that follow the cursor and blink, a logo re-scan, and a light on the cards.
(function () {
  const cfg = window.WASHQ_CONFIG || {};
  const stage = document.getElementById("stage");
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  if (cfg.USE_MOCK) {
    document.getElementById("demoBadge").hidden = false;
  }

  stage.classList.add("play");

  document.querySelectorAll(".role").forEach((card) => {
    card.addEventListener("click", (e) => {
      // Let new-tab clicks behave normally.
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
      e.preventDefault();
      document.getElementById("wipeTitle").textContent = "Opening " + card.dataset.target + "…";
      stage.classList.add("leaving");
      setTimeout(() => { window.location.href = card.getAttribute("href"); }, reduce ? 0 : 680);
    });
    // Light that follows the cursor inside the card.
    card.addEventListener("pointermove", (e) => {
      const r = card.getBoundingClientRect();
      card.style.setProperty("--mx", (e.clientX - r.left) + "px");
      card.style.setProperty("--my", (e.clientY - r.top) + "px");
    });
  });

  // Coming back with the browser's Back button shows the page again, not the curtain.
  window.addEventListener("pageshow", (e) => {
    if (e.persisted) stage.classList.remove("leaving");
  });

  if (reduce) return;

  /* ---------- Logo eyes follow the cursor, and blink now and then ---------- */
  const eyes = document.getElementById("eyes");
  const logo = document.querySelector(".landing .logo");
  let ex = 0, ey = 0, blinking = false;
  function placeEyes() {
    const blink = blinking ? " translate(50 49.5) scale(1 0.15) translate(-50 -49.5)" : "";
    eyes.setAttribute("transform", `translate(${ex.toFixed(2)} ${ey.toFixed(2)})${blink}`);
  }
  window.addEventListener("pointermove", (e) => {
    const r = logo.getBoundingClientRect();
    const cx = r.left + r.width * 0.2, cy = r.top + r.height * 0.5;
    const dx = e.clientX - cx, dy = e.clientY - cy;
    const d = Math.hypot(dx, dy) || 1;
    const k = Math.min(1, d / 300);
    ex = (dx / d) * 5 * k;
    ey = (dy / d) * 3 * k;
    placeEyes();
  });
  (function blinkLoop() {
    setTimeout(() => {
      blinking = true; placeEyes();
      setTimeout(() => { blinking = false; placeEyes(); blinkLoop(); }, 130);
    }, 3500 + Math.random() * 3000);
  })();

  /* ---------- Logo re-scan every few seconds ---------- */
  const scan = document.querySelector(".landing .logo .scan");
  const scanEyes = document.querySelector(".landing .logo .eyes-scan");
  const idleEyes = document.querySelector(".landing .logo .eyes-idle");
  if (scan.animate) {
    setInterval(() => {
      if (document.hidden || stage.classList.contains("leaving")) return;
      scan.animate([
        { top: "6px", opacity: 0 }, { opacity: 1, offset: 0.12 },
        { opacity: 1, offset: 0.85 }, { top: "calc(100% - 8px)", opacity: 0 }
      ], { duration: 1100, easing: "ease-in-out" });
      scanEyes.animate([{ opacity: 0 }, { opacity: 1, offset: 0.2 }, { opacity: 1, offset: 0.75 }, { opacity: 0 }], { duration: 1100 });
      idleEyes.animate([{ opacity: 1 }, { opacity: 0, offset: 0.2 }, { opacity: 0, offset: 0.75 }, { opacity: 1 }], { duration: 1100 });
    }, 9000);
  }
})();
