// Security Logs: one row per scan. Rows expand to show the details.
// No original text or sensitive values are shown or stored.
(function () {
  const api = window.WashqAPI;
  const B = window.WashqBrand;
  const $ = (s) => document.querySelector(s);
  const nf = new Intl.NumberFormat("en-US");
  const PAGE_SIZE = 10;

  // Every type code the backend can record (backend/app/labels.py TYPE_LABELS).
  const TYPE_OPTIONS = [
    ["PERSON_NAME", "Person name"], ["NATIONAL_ID", "National ID"], ["IQAMA", "Iqama number"],
    ["PHONE", "Phone number"], ["EMAIL", "Email address"], ["IBAN", "IBAN"], ["CARD_NUMBER", "Card number"],
    ["CARD_CVV", "Card security code"], ["ACCOUNT_NUMBER", "Account number"], ["SSN", "Social Security number"],
    ["USERNAME", "Username"], ["PASSWORD", "Password"], ["STREET_ADDRESS", "Street address"],
    ["IP_ADDRESS", "IP address"], ["CONFIDENTIAL", "Confidential topic"]
  ];

  const f = { decision: $("#fDecision"), type: $("#fType"), days: $("#fDays"), q: $("#fSearch") };
  TYPE_OPTIONS.forEach(([v, l]) => { const o = document.createElement("option"); o.value = v; o.textContent = l; f.type.append(o); });
  if (api.isMock) $("#demoBadge").hidden = false;

  // Filters can arrive from the dashboard, e.g. logs.html?decision=BLOCK&days=7
  const params = new URLSearchParams(location.search);
  const setIf = (sel, v) => { if (v && [...sel.options].some((o) => o.value === v)) sel.value = v; };
  setIf(f.decision, params.get("decision"));
  setIf(f.type, params.get("type"));
  setIf(f.days, params.get("days"));
  if (params.get("q")) f.q.value = params.get("q");

  const open = new Set(params.get("open") ? [params.get("open")] : []);
  let page = 1;
  let lastTotal = 0;
  let timer = null;
  let requestNo = 0;

  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const shortTime = (iso) => new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
  const longTime = (iso) => new Date(iso).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "medium", hour12: false });
  const CHEVRON = '<svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  function badge(decision) {
    return decision === "BLOCK"
      ? '<span class="badge s-block"><b aria-hidden="true">✕</b>BLOCK</span>'
      : '<span class="badge s-allow"><b aria-hidden="true">✓</b>ALLOW</span>';
  }
  function typeChips(detected, withCount) {
    return detected.length
      ? detected.map((d) => `<span class="chip">${esc(d.label)}${withCount || d.count > 1 ? " × " + d.count : ""}</span>`).join("")
      : '<span class="muted">None</span>';
  }

  function rows(e) {
    const id = esc(e.operation_id);
    const isOpen = open.has(e.operation_id);
    const masking = /masked/.test(e.masking) ? esc(e.masking) : `<span class="muted">${esc(e.masking)}</span>`;
    const main = `<tr class="row${isOpen ? " open" : ""}" data-id="${id}">
      <td><button type="button" class="xbtn" aria-expanded="${isOpen}" aria-controls="d-${id}" aria-label="Show details for ${id}">${CHEVRON}</button></td>
      <td class="time">${shortTime(e.time)}</td>
      <td>${typeChips(e.detected)}</td>
      <td>${badge(e.decision)}</td>
      <td>${masking}</td>
      <td class="mono">${id}</td>
    </tr>`;
    const sent = e.decision === "ALLOW" ? "Not needed, the text was clean" : (/masked/.test(e.masking) ? "Yes, a masked copy" : "No");
    const detail = `<tr class="detail" id="d-${id}"${isOpen ? "" : " hidden"}><td colspan="6">
      <dl class="detail-grid">
        <div class="wide"><dt>Reason</dt><dd>${esc(e.reason)}</dd></div>
        <div><dt>Detected data types</dt><dd>${typeChips(e.detected, true)}</dd></div>
        <div><dt>Masking result</dt><dd>${esc(e.masking)}</dd></div>
        <div><dt>Masked copy returned</dt><dd>${sent}</dd></div>
        <div><dt>Operation ID</dt><dd class="mono" style="font-family:var(--mono);font-size:12px">${id}</dd></div>
        <div><dt>Time</dt><dd>${longTime(e.time)}</dd></div>
        <div><dt>Decision</dt><dd>${badge(e.decision)}</dd></div>
        <p class="detail-note">${B.mark(12)}The original text and sensitive values are not stored, so they can’t be shown here.</p>
      </dl>
    </td></tr>`;
    return main + detail;
  }

  function toggle(tr) {
    const id = tr.dataset.id;
    const detail = document.getElementById("d-" + id);
    const btn = tr.querySelector(".xbtn");
    const nowOpen = detail.hidden;
    detail.hidden = !nowOpen;
    tr.classList.toggle("open", nowOpen);
    btn.setAttribute("aria-expanded", String(nowOpen));
    if (nowOpen) open.add(id); else open.delete(id);
  }

  $("#rows").addEventListener("click", (e) => {
    const tr = e.target.closest("tr.row");
    if (tr) toggle(tr);
  });

  async function render() {
    const mine = ++requestNo;
    try {
      const res = await api.logs({
        decision: f.decision.value, type: f.type.value, days: f.days.value,
        q: f.q.value.trim(), page, page_size: PAGE_SIZE
      });
      if (mine !== requestNo) return; // a newer filter change is on its way
      lastTotal = res.total;
      $("#rows").innerHTML = res.items.length
        ? res.items.map(rows).join("")
        : '<tr class="empty-row"><td colspan="6">No events match these filters. Try a longer period or reset the filters.</td></tr>';
      const from = res.total ? (page - 1) * PAGE_SIZE + 1 : 0;
      const to = Math.min(page * PAGE_SIZE, res.total);
      $("#count").textContent = `Showing ${nf.format(from)}–${nf.format(to)} of ${nf.format(res.total)}`;
      $("#prev").disabled = page <= 1;
      $("#next").disabled = to >= res.total;
    } catch (e) {
      if (mine !== requestNo) return;
      $("#rows").innerHTML = `<tr class="empty-row"><td colspan="6">Couldn’t load the logs. ${esc(e.message)}</td></tr>`;
      $("#count").textContent = "";
    }
  }

  function syncUrl() {
    const p = new URLSearchParams();
    if (f.decision.value) p.set("decision", f.decision.value);
    if (f.type.value) p.set("type", f.type.value);
    if (f.days.value !== "7") p.set("days", f.days.value);
    if (f.q.value.trim()) p.set("q", f.q.value.trim());
    const s = p.toString();
    try { history.replaceState(null, "", s ? "?" + s : location.pathname); } catch (e) { /* not important */ }
  }
  function refilter() { page = 1; syncUrl(); render(); }

  [f.decision, f.type, f.days].forEach((s) => s.addEventListener("change", refilter));
  f.q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(refilter, 250); });
  $("#filters").addEventListener("submit", (e) => { e.preventDefault(); refilter(); });
  $("#fReset").addEventListener("click", () => {
    f.decision.value = ""; f.type.value = ""; f.days.value = "7"; f.q.value = "";
    refilter();
  });
  $("#prev").addEventListener("click", () => { if (page > 1) { page--; render(); } });
  $("#next").addEventListener("click", () => { if (page * PAGE_SIZE < lastTotal) { page++; render(); } });

  render();
})();
