// Demo backend that runs in the browser, so the pages work before the real API exists.
// It follows the same request and response shapes as API_CONTRACT.md.
// The detection here is a few simple patterns for the demo only. It is not the real detector.
// ALLOW = nothing sensitive. BLOCK = sensitive data found; every value is masked and the masked copy is returned.
(function () {
  const cfg = window.WASHQ_CONFIG || {};
  const DAY = 86400000;

  const TYPES = {
    PERSON_NAME:  { label: "Person name",        plural: "person names" },
    NATIONAL_ID:  { label: "National ID",        plural: "national IDs" },
    PHONE:        { label: "Phone number",       plural: "phone numbers" },
    EMAIL:        { label: "Email address",      plural: "email addresses" },
    IBAN:         { label: "IBAN",               plural: "IBANs" },
    CARD_NUMBER:  { label: "Card number",        plural: "card numbers" },
    PASSWORD:     { label: "Password",           plural: "passwords" },
    CONFIDENTIAL: { label: "Confidential topic", plural: "confidential topics" }
  };
  const STOP = new Set(("Customer Customers Client Clients Service Services Human Resources Team Finance Sales Support " +
    "Thank Thanks Dear Best Kind Regards Hello Hi Please The This That These Those Review Summarize Draft Write " +
    "Translate Explain Make Help Can Could Would Why What How When Where Who Our My Your We They I If And Or But " +
    "For With Also Note Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March April May " +
    "June July August September October November December Invoice Contract Project Saudi Arabia Riyadh Jeddah New " +
    "York United States Kingdom Microsoft Google Excel Word Power Point AI ID IT HR WASHQ Confidential Internal List Board").split(" "));

  const RULES = [
    { type: "EMAIL",       re: /[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+/g },
    { type: "CARD_NUMBER", re: /\b(?:\d{4}[ -]?){3}\d{4}\b/g },
    { type: "IBAN",        re: /\bSA\d{2}(?:\s?[A-Z0-9]{4}){5}\b/gi },
    { type: "NATIONAL_ID", re: /\b[12]\d{9}\b/g },
    { type: "PHONE",       re: /(?:\+9665|\b05)\d{8}\b/g },
    { type: "PASSWORD",    re: /\b(?:password|passcode|pwd|pin)\b\s*(?:is|:|=)?\s*(\S+)/gi, group: 1 },
    { type: "PERSON_NAME", re: /\b([A-Z][a-z]+)\s+([A-Z][a-z]+)\b/g, name: true }
  ];

  // ---------- helpers ----------
  const clone = (v) => JSON.parse(JSON.stringify(v));
  const wait = (value, ms) => new Promise((resolve) => setTimeout(() => resolve(clone(value)), ms == null ? (cfg.MOCK_DELAY_MS || 900) : ms));
  const fail = (message, ms) => new Promise((_, reject) => setTimeout(() => reject(new Error(message)), ms || 300));
  const startOfDay = (t) => { const d = new Date(t); d.setHours(0, 0, 0, 0); return d.getTime(); };
  const localDate = (t) => { const d = new Date(t); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
  const maskingText = (n) => n ? `${n} ${n === 1 ? "item" : "items"} masked` : "No changes";

  function detect(text) {
    const found = [];
    RULES.forEach((rule) => {
      rule.re.lastIndex = 0;
      let m;
      while ((m = rule.re.exec(text))) {
        if (rule.name && (STOP.has(m[1]) || STOP.has(m[2]))) {
          rule.re.lastIndex = m.index + m[1].length + 1; // try again from the second word
          continue;
        }
        let start = m.index;
        let value = m[0];
        if (rule.group) { value = m[rule.group]; start = m.index + m[0].lastIndexOf(value); }
        value = value.replace(/[.,;:!?)]+$/, "");
        if (value) found.push({ start, end: start + value.length, type: rule.type });
      }
    });
    // Keep the longest match where two overlap.
    found.sort((a, b) => (b.end - b.start) - (a.end - a.start));
    const kept = [];
    found.forEach((s) => { if (!kept.some((k) => s.start < k.end && k.start < s.end)) kept.push(s); });
    return kept.sort((a, b) => a.start - b.start);
  }

  function summarize(spans) {
    const counts = {};
    spans.forEach((s) => { counts[s.type] = (counts[s.type] || 0) + 1; });
    return Object.keys(counts).map((type) => ({ type, label: TYPES[type].label, count: counts[type] }));
  }

  function mask(text, spans) {
    let out = text;
    [...spans].sort((a, b) => b.start - a.start).forEach((s) => { out = out.slice(0, s.start) + `[${s.type}]` + out.slice(s.end); });
    return out;
  }

  // ---------- demo history (same list feeds the dashboard and the logs) ----------
  function rng(seed) {
    return function () {
      seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function pickTypes(r) {
    const pool = ["PERSON_NAME", "PERSON_NAME", "PERSON_NAME", "PERSON_NAME", "NATIONAL_ID", "NATIONAL_ID", "NATIONAL_ID",
      "PHONE", "PHONE", "PHONE", "EMAIL", "EMAIL", "IBAN", "CARD_NUMBER", "PASSWORD"];
    const k = 1 + Math.floor(r() * 3);
    const out = {};
    for (let i = 0; i < k; i++) {
      const t = pool[Math.floor(r() * pool.length)];
      out[t] = (out[t] || 0) + 1 + (t === "PERSON_NAME" ? Math.floor(r() * 2) : 0);
    }
    return Object.keys(out).map((type) => ({ type, label: TYPES[type].label, count: out[type] }));
  }

  function buildHistory() {
    const now = Date.now();
    const today = startOfDay(now);
    const list = [];
    for (let d = 29; d >= 0; d--) {
      const dayStart = today - d * DAY;
      const r = rng(Math.floor(dayStart / DAY) + 7);
      const weekend = [5, 6].includes(new Date(dayStart).getDay()); // Fri, Sat
      const count = (weekend ? 4 : 16) + Math.floor(r() * (weekend ? 5 : 12));
      for (let i = 0; i < count; i++) {
        const t = dayStart + 8 * 3600000 + Math.floor(r() * 9 * 3600000);
        if (t > now) continue;
        const detected = r() < 0.25 ? [] : pickTypes(r);
        const n = detected.reduce((a, b) => a + b.count, 0);
        const e = n
          ? { detected, decision: "BLOCK", reason: "Sensitive data found, masked copy returned", masking: maskingText(n) }
          : { detected, decision: "ALLOW", reason: "No sensitive data found", masking: maskingText(0) };
        e.t = t;
        list.push(e);
      }
    }
    list.sort((a, b) => a.t - b.t);
    list.forEach((e, i) => { e.operation_id = "WSQ-" + String(i + 1).padStart(6, "0"); });
    return list;
  }

  // Scans made in this browser during the demo are added to the same history.
  const STORE_KEY = "washq_demo_events_v4";
  function loadSession() {
    try { return JSON.parse(localStorage.getItem(STORE_KEY) || "[]"); } catch (e) { return []; }
  }
  function saveSession() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(session.slice(-300))); } catch (e) { /* demo only */ }
  }

  const history = buildHistory();
  const session = loadSession().filter((e) => e.decision === "ALLOW" || e.decision === "BLOCK");

  function allEvents() { return history.concat(session); }
  function nextId() { return "WSQ-" + String(history.length + session.length + 1).padStart(6, "0"); }
  function publicEvent(e) {
    return { operation_id: e.operation_id, time: new Date(e.t).toISOString(), detected: e.detected,
      decision: e.decision, reason: e.reason, masking: e.masking };
  }

  // ---------- API: POST /api/check ----------
  function check(text) {
    if (!text || !text.trim()) return fail("The text is empty.");
    const spans = detect(text);
    const detected = summarize(spans);
    const id = nextId();
    // ALLOW = clean text. BLOCK = sensitive data found: the original is blocked and a masked copy is returned.
    const decision = spans.length ? "BLOCK" : "ALLOW";
    const reason = spans.length ? "Sensitive data found, masked copy returned" : "No sensitive data found";
    const masking = maskingText(spans.length);

    session.push({ operation_id: id, t: Date.now(), detected, decision, reason, masking });
    saveSession();

    return wait({
      operation_id: id,
      decision,
      reason,
      detected,
      safe_text: mask(text, spans),
      spans: spans.map((s) => ({ start: s.start, end: s.end, type: s.type })),
      pattern_hints: []
    });
  }

  // ---------- API: GET /api/stats ----------
  function stats(days) {
    days = Math.max(1, Math.min(90, +days || 7));
    const since = startOfDay(Date.now()) - (days - 1) * DAY;
    const list = allEvents().filter((e) => e.t >= since);
    const daily = [];
    for (let i = 0; i < days; i++) {
      const ds = since + i * DAY;
      const row = { date: localDate(ds), allow: 0, block: 0 };
      list.forEach((e) => { if (e.t >= ds && e.t < ds + DAY) row[e.decision === "BLOCK" ? "block" : "allow"]++; });
      daily.push(row);
    }
    const typeCounts = {};
    list.forEach((e) => e.detected.forEach((d) => { typeCounts[d.type] = (typeCounts[d.type] || 0) + d.count; }));
    const top_types = Object.keys(typeCounts)
      .map((type) => ({ type, label: TYPES[type].label, count: typeCounts[type] }))
      .sort((a, b) => b.count - a.count).slice(0, 6);
    return wait({
      days,
      total: list.length,
      allowed: list.filter((e) => e.decision === "ALLOW").length,
      blocked: list.filter((e) => e.decision === "BLOCK").length,
      daily,
      top_types,
      latest: [...list].sort((a, b) => b.t - a.t).slice(0, 6).map(publicEvent)
    }, 250);
  }

  // ---------- API: GET /api/logs ----------
  function logs(params) {
    const p = params || {};
    const days = +p.days || 7;
    const since = startOfDay(Date.now()) - (days - 1) * DAY;
    const q = (p.q || "").trim().toUpperCase();
    let list = allEvents().filter((e) => e.t >= since);
    if (p.decision) list = list.filter((e) => e.decision === p.decision);
    if (p.type) list = list.filter((e) => e.detected.some((d) => d.type === p.type));
    if (q) list = list.filter((e) => e.operation_id.includes(q));
    list.sort((a, b) => b.t - a.t);
    const page_size = +p.page_size || 10;
    const page = Math.max(1, +p.page || 1);
    return wait({ total: list.length, page, page_size,
      items: list.slice((page - 1) * page_size, page * page_size).map(publicEvent) }, 200);
  }

  window.WashqMock = { check, stats, logs };
})();
