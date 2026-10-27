// Employee workspace: the employee enters text and WASHQ's backend checks it.
//   ALLOW = nothing sensitive: the text can be used as it is.
//   BLOCK = sensitive data was found: the original must not be shared, so WASHQ returns a masked copy to use instead.
// WASHQ never sends the text to an AI model.
(function () {
  const api = window.WashqAPI;
  const B = window.WashqBrand;
  const $ = (s) => document.querySelector(s);

  const chat = $("#chat");
  const thread = $("#thread");
  const form = $("#composer");
  const inbox = form.querySelector(".inbox");
  const input = $("#msg");
  const sendBtn = $("#sendBtn");
  const errorBox = $("#formError");
  const guard = $("#guard");

  const MOTION = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const sleep = (ms) => new Promise((r) => setTimeout(r, MOTION ? ms : 0));
  const GUARD_DEFAULT = "Never sent to an AI model.";
  let busy = false;

  if (api.isMock) $("#demoBadge").hidden = false;

  const SAMPLES = [
    { hint: "Name + ID", text: "Summarize the complaint from customer Ahmed Alotaibi, ID 1098765432, about invoice #4471." },
    { hint: "Phone + email", text: "Please call Sara Alharbi on 0551234567 or email sara.alharbi@example.com about the contract renewal." },
    { hint: "Password + card", text: "The client can't log in. Their password is Riyadh@2024 and card 4111 1111 1111 1111 was declined." },
    { hint: "Nothing sensitive", text: "Draft a polite reply to a customer asking about a delayed refund." }
  ];

  // ---------- small DOM helpers ----------
  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function button(label, primary, onClick) {
    const b = el("button", "btn" + (primary ? " p" : ""), label);
    b.type = "button";
    b.addEventListener("click", onClick);
    return b;
  }
  function scrollDown() { chat.scrollTo({ top: chat.scrollHeight, behavior: MOTION ? "smooth" : "auto" }); }
  function setGuard(text, active) {
    guard.innerHTML = B.mark(12);
    guard.append(text);
    guard.classList.toggle("active", !!active);
  }
  function setBusy(on) {
    busy = on;
    sendBtn.classList.toggle("busy", on);
    sendBtn.setAttribute("aria-busy", String(on));
  }
  function autoGrow() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 180) + "px"; }
  function showError(text) { errorBox.textContent = text; errorBox.hidden = false; }
  function hideError() { errorBox.hidden = true; }
  function enter(node) { if (MOTION) node.classList.add("enter"); return node; }

  function chips(detected) {
    const box = el("div", "chips");
    detected.forEach((d) => box.append(el("span", "chip", `${d.label} × ${d.count}`)));
    return box;
  }
  function block(label, content) {
    const s = el("div");
    s.append(el("span", "k", label));
    if (content) s.append(content);
    return s;
  }
  const total = (detected) => detected.reduce((a, d) => a + d.count, 0);

  // Text with [LABELS] shown as tags.
  function labelled(text) {
    const frag = document.createDocumentFragment();
    const re = /\[([A-Z_]+)\]/g;
    let last = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > last) frag.append(text.slice(last, m.index));
      frag.append(el("span", "lab", m[0]));
      last = re.lastIndex;
    }
    if (last < text.length) frag.append(text.slice(last));
    return frag;
  }

  // ---------- welcome + sample texts ----------
  function welcome() {
    const w = el("section", "welcome");
    w.innerHTML = B.mascot("idle", 60);
    w.append(el("h1", null, "Paste text to make it safe"));
    const list = el("div", "suggest short");
    SAMPLES.forEach((s) => {
      const b = el("button", "sugg");
      b.type = "button";
      b.title = s.text;
      b.append(s.hint);
      b.addEventListener("click", () => {
        input.value = s.text;
        autoGrow();
        hideError();
        form.classList.remove("needs-edit");
        if (MOTION) { inbox.classList.remove("filled"); void inbox.offsetWidth; inbox.classList.add("filled"); }
        input.focus();
      });
      list.append(b);
    });
    w.append(list);
    thread.append(w);
  }

  // ---------- scanning ----------
  function scanning() {
    inbox.classList.add("scanning");
    input.readOnly = true;
    setGuard("Scanning…", true);

    const card = enter(el("div", "scan"));
    card.setAttribute("role", "status");
    card.innerHTML = B.mascot("scan", 40);
    const body = el("div");
    body.append(el("b", null, "Scanning…"));
    const track = el("div", "track");
    track.append(el("div", "run"));
    body.append(track);
    card.append(body);
    thread.append(card);
    scrollDown();

    return async function stop() {
      inbox.classList.remove("scanning");
      input.readOnly = false;
      if (MOTION) { card.classList.add("leave"); await sleep(200); }
      card.remove();
    };
  }

  // ---------- the employee's text, with values turning into placeholders ----------
  function userBubble(text) {
    const wrap = enter(el("div", "msg user"));
    const bubble = el("div", "bubble");
    bubble.append(text);
    wrap.append(bubble);
    thread.append(wrap);
    scrollDown();
    return { wrap, bubble };
  }

  async function maskInBubble(bubble, original, r) {
    const spans = (r.spans || []).slice().sort((a, b) => a.start - b.start);
    // Without positions (or without motion), just show the safe text.
    if (!spans.length || !MOTION) { bubble.textContent = ""; bubble.append(labelled(r.safe_text)); return; }

    bubble.textContent = "";
    const marks = [];
    let last = 0;
    spans.forEach((s) => {
      if (s.start < last) return;
      if (s.start > last) bubble.append(original.slice(last, s.start));
      const m = el("span", "mv", original.slice(s.start, s.end));
      m.dataset.label = `[${s.type}]`;
      bubble.append(m);
      marks.push(m);
      last = s.end;
    });
    if (last < original.length) bubble.append(original.slice(last));

    await sleep(260);
    for (const m of marks) {
      m.classList.add("out");
      await sleep(170);
      m.textContent = m.dataset.label;
      m.className = "lab pop";
      await sleep(140);
    }
    // Make sure what's on screen is exactly the sanitized text the backend returned.
    await sleep(120);
    bubble.textContent = "";
    bubble.append(labelled(r.safe_text));
  }

  function meta(wrap, text) {
    const m = el("div", "meta");
    m.innerHTML = B.mark(11);
    m.append(text);
    wrap.append(m);
  }

  // ---------- result cards ----------
  function resultCard(state, pill, title, sub) {
    const card = enter(el("div", "chk s-" + state));
    const head = el("div", "chk-h");
    head.innerHTML = B.mascot(state, 36);
    const t = el("div");
    t.append(el("span", "title", title));
    if (sub) t.append(el("span", "sub", sub));
    head.append(t, el("span", "pill", pill));
    const body = el("div", "chk-b");
    card.append(head, body);
    return { card, body };
  }

  // Copies text to the clipboard, with a fallback for pages opened from a file.
  async function copyText(text) {
    try {
      // Some browsers never settle this promise (e.g. a blocked permission), so don't wait forever.
      await Promise.race([navigator.clipboard.writeText(text),
        new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), 1000))]);
      return true;
    } catch (e) { /* try the fallback */ }
    const ta = el("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.append(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { /* not supported */ }
    ta.remove();
    return ok;
  }

  // ALLOW: show the detected types and the sanitized text, ready to copy.
  // ALLOW: clean text, ready to copy as it is. BLOCK with a masked copy: the original is blocked, the masked copy can be used.
  function resultWithCopy(r) {
    const n = total(r.detected);
    const { card, body } = r.decision === "BLOCK"
      ? resultCard("block", "BLOCK", `Sensitive data found · ${n} ${n === 1 ? "item" : "items"} masked`, "Don’t share the original. Use this masked copy.")
      : resultCard("allow", "ALLOW", "Nothing sensitive", "Your text is safe to share as it is.");
    if (r.detected.length) body.append(chips(r.detected));
    const safe = el("div", "safe-text");
    safe.append(labelled(r.safe_text));
    body.append(safe);

    let resetCopy;
    const copy = button("Copy", true, async () => {
      const ok = await copyText(r.safe_text);
      copy.textContent = ok ? "Copied ✓" : "Select the text to copy";
      clearTimeout(resetCopy);
      resetCopy = setTimeout(() => { copy.textContent = "Copy"; }, 1800);
    });
    const acts = el("div", "acts");
    acts.append(copy);
    body.append(acts);
    thread.append(card);
    scrollDown();
    return card;
  }

  // BLOCK: the backend returned no sanitized text, so there is nothing to copy.
  function blockCard(r) {
    const { card, body } = resultCard("block", "BLOCK", "Can’t make this text safe");
    if (r.reason) body.append(el("div", null, r.reason));
    if (r.detected.length) body.append(chips(r.detected));
    const edit = button("Edit text", true, () => {
      form.classList.add("needs-edit");
      setGuard("Edit, then scan again.");
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
    });
    const acts = el("div", "acts");
    acts.append(edit);
    body.append(acts);
    thread.append(card);
    scrollDown();
    return card;
  }

  // Only a complete ALLOW or BLOCK answer is shown as a result; anything else is treated as a failed scan.
  function validCheck(r) {
    if (!r || typeof r.operation_id !== "string" || !Array.isArray(r.detected)) return false;
    if (r.decision === "ALLOW") return typeof r.safe_text === "string" && r.safe_text.trim() !== "";
    return r.decision === "BLOCK"; // with a masked copy (safe_text), or without one if it couldn't be masked
  }

  // Older result cards stay in the history, without their buttons.
  function retireOldCards() {
    thread.querySelectorAll(".chk .acts").forEach((a) => a.remove());
  }

  // ---------- send ----------
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (busy) return;
    const text = input.value.trim();
    if (!text) { showError("Paste some text first."); input.focus(); return; }
    hideError();
    form.classList.remove("needs-edit");
    retireOldCards();
    const w = thread.querySelector(".welcome");
    if (w) w.remove();

    setBusy(true);
    const stop = scanning();
    const started = Date.now();
    let r;
    try {
      r = await api.check(text);
      if (!validCheck(r)) throw new Error("The server sent an incomplete answer, so no result is shown.");
    } catch (err) {
      await stop();
      setBusy(false);
      setGuard(GUARD_DEFAULT);
      showError(`WASHQ couldn’t scan this text. ${err.message}`);
      return;
    }
    await sleep(Math.max(0, 1200 - (Date.now() - started)));
    await stop();

    const hasCopy = typeof r.safe_text === "string" && r.safe_text.trim() !== "";
    if (hasCopy) {
      setGuard(GUARD_DEFAULT);
      input.value = "";
      autoGrow();
      const { wrap, bubble } = userBubble(text);
      await maskInBubble(bubble, text, r);
      const n = total(r.detected);
      meta(wrap, n ? `${n} masked` : "Checked");
      await sleep(120);
      resultWithCopy(r);
    } else {
      // BLOCK without a masked copy: nothing to copy. The text stays in the box so the employee can edit it.
      setGuard("Edit, then scan again.");
      blockCard(r);
    }
    setBusy(false);
  });

  input.addEventListener("input", () => { autoGrow(); hideError(); form.classList.remove("needs-edit"); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      form.requestSubmit();
    }
  });

  setGuard(GUARD_DEFAULT);
  welcome();
  input.focus();
})();
